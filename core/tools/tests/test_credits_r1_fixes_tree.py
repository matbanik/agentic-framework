"""R1-F4: ``tree`` on a resume keeps the run's retained work (AC-F.2, AC-G.2).

Execution review round 1, finding 4: the first ``tree`` of a run fixes B and pins
the start tree S. The run then edits tracked files, stops and resumes. The resumed
segment runs ``tree`` again (``execution-session.md``: at every start or resume).
Before the fix that call ran the pristine-start content check (R§4.3 (b)) on the
retained edits and refused ``base_content_mismatch``.

The contract these tests fix:

* A first start keeps every refusal (``base_content_mismatch`` on a dirty tree).
* A continuation (the run has ``base_fixed`` and a start tree) keeps B, S, the
  retained edits and the recorded carry manifest. It checks only that HEAD is still
  B (``base_moved``), that ``CREDITS_BASE_COMMIT`` names the fixed B (``base_fixed``),
  that the tree is the recorded one (``active_tree_mismatch``) and that the pinned
  start ref is S.

Every test runs the real store and the real run-side tool in subprocesses against
a temp store, a temp config and a temp git repository, and the real worktree
helper in-process with only its venv step replaced. The chain rig is copied from
the project's chain tests (rigs are copied, never imported). Do not skip, only, or
early-return (G36).
"""

from __future__ import annotations

import importlib
import json
import shutil
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from test_credits_msg import CONFIG_DEFAULTS, MSG_TOOL, STATUS_FILES
from test_credits_state import (
    REAL_DB_STATE_AT_IMPORT,
    ROOT,
    SESSION_A,
    Out,
    Store,
    accept_args,
    at,
    child_env,
    launched_args,
    parse_out,
    real_db_state,
    request_args,
)

MARK = "CREDITS_R1_TREE"
STATUS = STATUS_FILES[0]
KNOWN_ISSUES = ".agent/context/known-issues.yaml"
GROUPING = ".agent/context/grouping/fixture-grouping.md"
DAY = "2026-10-16"
# The adopter config the worktree helper reads from the main tree. The fixture has
# no venv, so ``venv_build`` is null.
WORKTREE_CONFIG = ".agent/credits/worktree.json"
WORKTREE_CONFIG_BODY = (
    '{"env_files": [], "frozen_dirs": [], "venv_build": null, "linked_trees": []}\n'
)


def plan_dir(run_id: str) -> str:
    return f"docs/execution/plans/{DAY}-{run_id}/"


def handoff(run_id: str) -> str:
    return f".agent/context/handoffs/{DAY}-{run_id}-handoff.md"


def reflection(run_id: str) -> str:
    return f"docs/execution/reflections/{DAY}-{run_id}-reflection.md"


def closeout(run_id: str) -> tuple[str, str, str]:
    return (plan_dir(run_id), handoff(run_id), reflection(run_id))


def seg(run_id: str, n: int) -> str:
    return f"seg-{run_id}-{n}"


def git(repo: Path, *args: str) -> str:
    """Run one git command in ``repo``; return its stripped stdout."""
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=child_env({"GIT_CONFIG_NOSYSTEM": "1"}),
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, f"git {args}: {proc.stdout}{proc.stderr}"
    return proc.stdout.strip()


def put(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def make_repo(repo: Path) -> str:
    """A main tree with the three status files; return the first commit."""
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "Fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "core.autocrlf", "false")
    git(repo, "config", "commit.gpgsign", "false")
    put(repo, ".gitignore", "*.log\n.venv/\n")
    put(repo, "README.md", "fixture readme\n")
    put(repo, "src/a.py", "A = 1\n")
    put(repo, "src/b.py", "B = 2\n")
    put(repo, "src/c.py", "C = 3\n")
    put(repo, KNOWN_ISSUES, "issues: []\n")
    put(repo, GROUPING, "# grouping\n")
    put(repo, WORKTREE_CONFIG, WORKTREE_CONFIG_BODY)
    for rel in STATUS_FILES:
        put(repo, rel, f"status {rel}\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    return git(repo, "rev-parse", "HEAD")


@dataclass
class Chain:
    """A temp store, config and main tree, and the in-process helper."""

    st: Store
    repo: Path
    first: str
    config: Path
    work: Path
    tool: Any
    capsys: pytest.CaptureFixture[str]

    def manifest(self, run_id: str, *, worktree: bool | None = None) -> dict[str, Any]:
        root = self.repo.as_posix()
        doc: dict[str, Any] = {
            "schema": "credits-run.v1",
            "run_id": run_id,
            "kind": "exec",
            "project_root": root,
            "plan_folder": plan_dir(run_id),
            "brief": "C:/Temp/fixture/brief.md",
            "launch": {
                "working_directory": root,
                "claude_exe": "C:/fixture/claude.cmd",
                "python_exe": "C:/fixture/python.exe",
                "permission_mode": "bypassPermissions",
                "model": "fixture-model",
                "effort": "high",
                "segment_cap_usd": 75.0,
                "timeout_sec": 43200,
            },
            "budget": {"run_cap_usd": 200.0},
            "messaging": {
                "orchestrator_sessions": ["00000000-0000-4000-8000-0000000000aa"],
                "ruling_enabled": False,
                "gate_wait_max_min": 0,
            },
            "depends_on": [],
            "lane": f"tree:{root}",
        }
        if worktree is not None:
            doc["executor_worktree"] = worktree
        return doc

    def register(
        self, run_id: str, *, now: int = 0, worktree: bool | None = None
    ) -> None:
        path = self.work / f"manifest-{run_id}.json"
        path.write_text(
            json.dumps(self.manifest(run_id, worktree=worktree), indent=2),
            encoding="utf-8",
        )
        out = self.st.cli(
            "register",
            "--run-id",
            run_id,
            "--manifest",
            str(path),
            "--cli-version",
            "9.9.9",
            "--kit-revision",
            "kitrev-fixture",
            now=now,
        )
        assert out.code == 0 and out.result == "changed", out.show()
        self.st.ok(
            "registered", "--run-id", run_id, "--task-hash", f"th-{run_id}", now=now
        )

    def admitted(
        self, run_id: str, n: int, *, now: int, resume: bool = False
    ) -> dict[str, Any]:
        """Request, accept, admit and launch segment ``n``; return the admit payload."""
        self.st.ok("request", *request_args(run_id, n, resume=resume), now=now)
        accepted = self.st.ok("accept", *accept_args(run_id, n, SESSION_A), now=now + 5)
        assert accepted.get("outcome") == "accepted", accepted
        out = self.st.cli(
            "admit",
            "--attempt-id",
            f"att-{run_id}-{n}",
            "--segment-id",
            seg(run_id, n),
            now=now + 6,
        )
        assert out.code == 0 and out.payload is not None, out.show()
        assert out.payload.get("outcome") == "admitted", out.show()
        self.st.ok("launched", *launched_args(seg(run_id, n), now + 7), now=now + 7)
        return out.payload

    def finish(self, run_id: str, n: int, *, now: int) -> None:
        self.st.ok(
            "complete_segment",
            "--segment-id",
            seg(run_id, n),
            "--finalized-by",
            "launcher",
            "--class",
            "exited",
            "--session-total-usd",
            "1.0",
            now=now,
        )

    def classify(self, run_id: str, to: str, cls: str, *, now: int) -> None:
        self.st.ok("classify", "--run-id", run_id, "--to", to, "--class", cls, now=now)

    def msg(
        self,
        run_id: str,
        n: int,
        verb: str,
        *args: str,
        now: int,
        base: str | None = None,
    ) -> Out:
        env = self.st.env(
            {
                "CREDITS_RUN_ID": run_id,
                "CREDITS_SEGMENT": seg(run_id, n),
                "CREDITS_STATE_DB": str(self.st.db),
                "CREDITS_CONFIG": str(self.config),
                **({"CREDITS_BASE_COMMIT": base} if base else {}),
            }
        )
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", str(MSG_TOOL), "--now-utc", at(now), verb]
            + list(args),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=child_env(env),
            timeout=120,
            cwd=ROOT,
            check=False,
        )
        return parse_out(proc.returncode, proc.stdout, proc.stderr)

    def tree(
        self, run_id: str, n: int, path: Path, *, now: int, base: str | None
    ) -> Out:
        return self.msg(run_id, n, "tree", str(path), now=now, base=base)

    def capture(self, run_id: str, n: int, changed: list[str], *, now: int) -> Out:
        listing = self.work / f"changed-{run_id}-{now}.txt"
        listing.write_text("".join(f"{p}\n" for p in changed), encoding="utf-8")
        args = ["--part", "product", "--changed-files", str(listing)]
        for rel in closeout(run_id):
            args += ["--closeout", rel]
        return self.msg(run_id, n, "landing", *args, now=now)

    def seal(self, run_id: str, n: int, *, now: int) -> Out:
        return self.msg(run_id, n, "landing", "--part", "closeout", now=now)

    def write_closeout(self, run_id: str) -> None:
        put(self.repo, plan_dir(run_id) + "task.md", f"| H2 | {run_id} | `[x]` |\n")
        put(self.repo, handoff(run_id), f"# {run_id} handoff\n")
        put(self.repo, reflection(run_id), f"# {run_id} reflection\n")

    def helper(self, *argv: object) -> tuple[int, list[str]]:
        self.capsys.readouterr()
        try:
            code = self.tool.main(["--root", str(self.repo), *[str(a) for a in argv]])
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 2
        return code, self.capsys.readouterr().out.splitlines()

    def wt_path(self, slug: str) -> Path:
        return self.repo.parent / f"{self.repo.name}-wt-{slug}"

    def create(self, slug: str, *extra: str) -> Path:
        code, lines = self.helper("create", f"wt-{slug}", *extra)
        wt = self.wt_path(slug)
        assert code == 0 and lines[-1:] == [f"worktree_ready:{wt.as_posix()}"], (
            f"{MARK}: create {slug} exited {code} with {lines}"
        )
        return wt

    def land(self, wt: Path) -> list[str]:
        code, lines = self.helper("land", wt)
        assert code == 0, f"{MARK}: land exited {code} with {lines}"
        return lines

    def remove(self, wt: Path) -> None:
        code, lines = self.helper("remove", wt)
        assert (code, lines) == (0, [f"worktree_removed:{wt.as_posix()}"]), lines

    def run_row(self, run_id: str) -> dict[str, Any]:
        rows = self.st.rows("SELECT * FROM runs WHERE run_id = ?", (run_id,))
        assert len(rows) == 1, rows
        names = [r[1] for r in self.st.rows("PRAGMA table_info(runs)")]
        return dict(zip(names, rows[0], strict=True))

    def credits_refs(self, run_id: str) -> set[str]:
        listing = git(
            self.repo, "for-each-ref", "--format=%(refname)", f"refs/credits/{run_id}/"
        )
        return {line for line in listing.splitlines() if line}


@pytest.fixture
def ch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> Iterator[Chain]:
    tool = importlib.import_module("tools.executor_worktree")

    def fake_venv(path: Path) -> int:
        put(Path(path), ".venv/pyvenv.cfg", "home = stub\n")
        return 0

    monkeypatch.setattr(tool, "_build_venv", fake_venv)
    monkeypatch.delenv("CREDITS_BASE_COMMIT", raising=False)
    st = Store(tmp_path / "store")
    st.root.mkdir()
    st.init()
    repo = tmp_path / "repo"
    first = make_repo(repo)
    work = tmp_path / "work"
    work.mkdir()
    config = tmp_path / "config.json"
    config.write_text(json.dumps(CONFIG_DEFAULTS), encoding="utf-8")
    yield Chain(
        st=st,
        repo=repo,
        first=first,
        config=config,
        work=work,
        tool=tool,
        capsys=capsys,
    )
    for entry in tmp_path.iterdir():
        if entry.name.startswith(f"{repo.name}-"):
            shutil.rmtree(entry, ignore_errors=True)


def worktree_run(ch: Chain, run_id: str = "w") -> tuple[str, Path]:
    """A worktree run admitted at B, its worktree at B, tree done; return (B, wt)."""
    ch.register(run_id, worktree=True)
    base = str(ch.admitted(run_id, 1, now=1)["base_commit"])
    put(ch.repo, plan_dir(run_id) + "task.md", f"| 1 | {run_id} | `[ ]` |\n")
    wt = ch.create(run_id, "--base", base, "--carry", plan_dir(run_id))
    out = ch.tree(run_id, 1, wt, now=10, base=base)
    assert out.code == 0, out.show()
    return base, wt


def carry_manifest(ch: Chain, run_id: str, n: int) -> Any:
    raw = ch.st.one(
        "SELECT carry_manifest_json FROM segments WHERE segment_id = ?",
        (seg(run_id, n),),
    )
    return None if raw is None else json.loads(str(raw))


def start_ref(ch: Chain, run_id: str) -> str:
    return git(ch.repo, "rev-parse", f"refs/credits/{run_id}/start^{{tree}}")


def stop_and_resume(ch: Chain, run_id: str, *, now: int) -> dict[str, Any]:
    """Segment 1 ends, the run stops, segment 2 is admitted as a resume."""
    ch.finish(run_id, 1, now=now)
    ch.classify(run_id, "stopped", "context_exhausted", now=now + 1)
    return ch.admitted(run_id, 2, now=now + 10, resume=True)


def main_tree_run(ch: Chain, run_id: str = "m") -> str:
    """A main-tree run whose first ``tree`` fixed B; return the start tree S."""
    ch.register(run_id)
    ch.admitted(run_id, 1, now=1)
    out = ch.tree(run_id, 1, ch.repo, now=10, base=ch.first)
    assert out.code == 0 and out.result == "changed", out.show()
    row = ch.run_row(run_id)
    assert row["base_fixed"] == 1 and row["base_commit"] == ch.first
    return str(row["start_tree"])


# --- the finding: a resume keeps the retained edits -----------------------------------


def test_r1_f4_main_tree_resume_keeps_the_retained_tracked_edit(ch: Chain) -> None:
    """The reviewer's sequence: tree, a tracked edit, stop, resume, tree → exit 0."""
    start = main_tree_run(ch)
    manifest = carry_manifest(ch, "m", 1)
    put(ch.repo, "src/a.py", "A = 11\n")
    payload = stop_and_resume(ch, "m", now=50)
    assert payload["base_commit"] == ch.first

    out = ch.tree("m", 2, ch.repo, now=100, base=ch.first)
    assert out.code == 0, out.show()
    assert out.payload is not None
    assert out.payload["start_tree"] == start
    assert out.payload["carry_manifest"] == manifest
    row = ch.run_row("m")
    assert (row["start_tree"], row["base_commit"], row["base_fixed"]) == (
        start,
        ch.first,
        1,
    )
    assert start_ref(ch, "m") == start
    assert carry_manifest(ch, "m", 2) == manifest
    assert (ch.repo / "src/a.py").read_text(encoding="utf-8") == "A = 11\n"


def test_r1_f4_worktree_resume_keeps_the_retained_edits(ch: Chain) -> None:
    """A worktree run: a tracked edit and a new file survive the resume's tree."""
    base, wt = worktree_run(ch)
    start = str(ch.run_row("w")["start_tree"])
    manifest = carry_manifest(ch, "w", 1)
    put(wt, "src/b.py", "B = 20\n")
    put(wt, "README.md", "edited by the run\n")
    put(wt, "src/new.py", "NEW = 1\n")
    put(wt, plan_dir("w") + "task.md", "| 1 | w | `[x]` |\n")
    payload = stop_and_resume(ch, "w", now=50)
    assert payload["base_commit"] == base

    out = ch.tree("w", 2, wt, now=100, base=base)
    assert out.code == 0, out.show()
    assert out.payload is not None
    assert out.payload["start_tree"] == start
    assert out.payload["carry_manifest"] == manifest
    assert ch.run_row("w")["start_tree"] == start
    assert start_ref(ch, "w") == start
    assert carry_manifest(ch, "w", 2) == manifest
    assert (wt / "src/b.py").read_text(encoding="utf-8") == "B = 20\n"
    assert (wt / "src/new.py").read_text(encoding="utf-8") == "NEW = 1\n"


def test_r1_f4_worktree_resume_after_land_runs_to_the_seal(ch: Chain) -> None:
    """Edit, land, stop, resume: tree passes, then capture, remove and seal pass."""
    base, wt = worktree_run(ch)
    start = str(ch.run_row("w")["start_tree"])
    put(wt, "src/b.py", "B = 20\n")
    assert ch.land(wt) == ["land_ok:0:1:0"]
    stop_and_resume(ch, "w", now=50)

    out = ch.tree("w", 2, wt, now=100, base=base)
    assert out.code == 0, out.show()
    assert out.payload is not None and out.payload["start_tree"] == start
    out = ch.capture("w", 2, ["src/b.py"], now=110)
    assert out.code == 0 and out.result == "changed", out.show()
    ch.remove(wt)
    ch.write_closeout("w")
    out = ch.seal("w", 2, now=120)
    assert out.code == 0 and out.result == "changed", out.show()
    assert ch.credits_refs("w") == {
        f"refs/credits/w/{name}" for name in ("start", "landed", "capture", "sealed")
    }


def test_r1_f4_a_second_tree_in_the_same_segment_is_no_change(ch: Chain) -> None:
    """A retried tree after an edit, in the same segment, keeps S and writes nothing."""
    start = main_tree_run(ch)
    put(ch.repo, "src/a.py", "A = 11\n")
    out = ch.tree("m", 1, ch.repo, now=20, base=ch.first)
    assert out.code == 0 and out.result == "no_change", out.show()
    assert out.payload is not None and out.payload["start_tree"] == start


# --- the first start keeps every refusal ---------------------------------------------


def test_r1_f4_a_dirty_tree_at_the_first_start_is_still_refused(ch: Chain) -> None:
    """A tracked edit before the first tree: base_content_mismatch, nothing fixed."""
    ch.register("m")
    ch.admitted("m", 1, now=1)
    put(ch.repo, "src/a.py", "A = 11\n")
    out = ch.tree("m", 1, ch.repo, now=10, base=ch.first)
    assert out.code == 3 and out.error == "base_content_mismatch:src/a.py", out.show()
    row = ch.run_row("m")
    assert (row["start_tree"], row["base_fixed"]) == (None, 0)
    assert ch.credits_refs("m") == set()


def test_r1_f4_a_dirty_carried_file_at_the_first_start_is_still_refused(
    ch: Chain,
) -> None:
    """The worktree first start keeps check (c): base_carry_mismatch."""
    ch.register("w", worktree=True)
    base = str(ch.admitted("w", 1, now=1)["base_commit"])
    put(ch.repo, plan_dir("w") + "task.md", "| 1 | w | `[ ]` |\n")
    put(ch.repo, "src/c.py", "C = 33\n")
    wt = ch.create("w", "--base", base, "--carry", plan_dir("w"), "--carry", "src/c.py")
    out = ch.tree("w", 1, wt, now=10, base=base)
    assert out.code == 3 and out.error == "base_carry_mismatch:src/c.py", out.show()
    assert ch.run_row("w")["start_tree"] is None


# --- a continuation keeps the other checks -------------------------------------------


def test_r1_f4_a_moved_head_on_resume_is_base_moved(ch: Chain) -> None:
    """HEAD moved after the first tree: the resume's tree refuses base_moved."""
    start = main_tree_run(ch)
    put(ch.repo, STATUS, "status: moved\n")
    git(ch.repo, "commit", "-q", "-am", "the head moves")
    stop_and_resume(ch, "m", now=50)
    out = ch.tree("m", 2, ch.repo, now=100, base=ch.first)
    assert out.code == 3 and out.error == "base_moved", out.show()
    assert ch.run_row("m")["start_tree"] == start
    assert carry_manifest(ch, "m", 2) is None


def test_r1_f4_another_base_on_resume_is_base_fixed(ch: Chain) -> None:
    """CREDITS_BASE_COMMIT names another commit than the fixed B: base_fixed."""
    main_tree_run(ch)
    tree = git(ch.repo, "rev-parse", f"{ch.first}^{{tree}}")
    other = git(ch.repo, "commit-tree", tree, "-p", ch.first, "-m", "side commit")
    stop_and_resume(ch, "m", now=50)
    out = ch.tree("m", 2, ch.repo, now=100, base=other)
    assert out.code == 3 and out.error == "base_fixed", out.show()
    assert ch.run_row("m")["base_commit"] == ch.first


def test_r1_f4_another_worktree_on_resume_is_refused(ch: Chain) -> None:
    """The resume's tree in another helper worktree: active_tree_mismatch."""
    base, wt = worktree_run(ch)
    other = ch.create("other", "--base", base, "--carry", plan_dir("w"))
    stop_and_resume(ch, "w", now=50)
    out = ch.tree("w", 2, other, now=100, base=base)
    assert out.code == 3 and out.error == "active_tree_mismatch", out.show()
    row = ch.run_row("w")
    assert Path(str(row["active_tree"])).resolve() == wt.resolve()


def test_r1_f4_a_moved_start_ref_on_resume_is_refused(ch: Chain) -> None:
    """The pinned start ref no longer names S: start_ref_mismatch."""
    start = main_tree_run(ch)
    other = git(ch.repo, "rev-parse", f"{ch.first}:src")
    assert other != start
    git(ch.repo, "update-ref", "refs/credits/m/start", other)
    stop_and_resume(ch, "m", now=50)
    out = ch.tree("m", 2, ch.repo, now=100, base=ch.first)
    assert out.code == 3 and out.error == "start_ref_mismatch", out.show()


def test_real_store_unchanged() -> None:
    """AC-B.10 — no test here touched the real store."""
    assert real_db_state() == REAL_DB_STATE_AT_IMPORT
