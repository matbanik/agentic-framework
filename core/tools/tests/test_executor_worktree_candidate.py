"""B-3 tests: ``tools/executor_worktree.py`` recognizes a commit candidate (AC-C.11, V3-002).

FIC: ``the run-parameters design plan/implementation-plan.md`` AC-C.11;
R§4.5 and R§8 :1605; EA-8 (g).

A commit candidate is a detached worktree that ``tools/commit_batch.py`` builds for one op.
Its manifest is ``<candidate git dir>/candidate-worktree.json`` =
``{"schema": "candidate-worktree/1", "kind": "candidate", "op", "run_id", "plan"}``.
``remove`` deletes a candidate (its content never lands, so there is no ``unlanded`` check);
``check``, ``land`` and ``sync`` refuse it with ``worktree_bad:candidate``; a worktree with no
valid manifest of either kind is ``worktree_bad:manifest``.

Every test builds a real temp git repository; the tool's ``main()`` runs in-process. The rig is
local to this file (rigs are copied between test files, never imported). Multi-case tests run
their cases in sequence inside one function (no parametrize). Do not skip, only, or
early-return (G36).
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

MANIFEST = "candidate-worktree.json"
PLAN = "2026-10-17-fixture-plan"


def _env() -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("GIT_")
    }
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    return env


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert proc.returncode == 0, f"git {' '.join(args)}: {proc.stderr}"
    return proc.stdout.strip()


def _repo(tmp_path: Path) -> Path:
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q", "-b", "main")
    _git(main, "config", "user.name", "Fixture")
    _git(main, "config", "user.email", "fixture@example.invalid")
    _git(main, "config", "commit.gpgsign", "false")
    (main / "base.txt").write_bytes(b"base\n")
    _git(main, "add", "--", "base.txt")
    _git(main, "commit", "-q", "-m", "fixture: base")
    return main


def _manifest(op: str) -> dict[str, Any]:
    return {
        "schema": "candidate-worktree/1",
        "kind": "candidate",
        "op": op,
        "run_id": "interactive",
        "plan": PLAN,
    }


def _candidate(main: Path, tmp_path: Path, name: str, manifest: bytes | None) -> Path:
    """A detached worktree of ``main``; ``manifest`` bytes go to its git dir when given."""
    path = tmp_path / "candidates" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    _git(main, "worktree", "add", "-q", "--detach", str(path), "HEAD")
    if manifest is not None:
        git_dir = Path(_git(path, "rev-parse", "--absolute-git-dir"))
        (git_dir / MANIFEST).write_bytes(manifest)
    return path


def _listed(main: Path) -> set[str]:
    listing = _git(main, "worktree", "list", "--porcelain")
    return {
        line[len("worktree ") :].replace("\\", "/").lower()
        for line in listing.splitlines()
        if line.startswith("worktree ")
    }


def _tool() -> ModuleType:
    return importlib.import_module("tools.executor_worktree")


def _main(
    capsys: pytest.CaptureFixture[str], main: Path, *argv: str
) -> tuple[int, list[str]]:
    capsys.readouterr()
    code = _tool().main(["--root", str(main), *argv])
    lines = [line for line in capsys.readouterr().out.splitlines() if line]
    return code, lines


def test_vec_v3_002_remove_deletes_a_dirty_candidate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-C.11: ``remove`` recognizes the candidate manifest and deletes a dirty candidate."""
    main = _repo(tmp_path)
    data = json.dumps(_manifest("op-1")).encode("utf-8")
    path = _candidate(main, tmp_path, "op-1", data)
    (path / "base.txt").write_bytes(b"changed\n")
    (path / "staged.txt").write_bytes(b"staged\n")
    _git(path, "add", "--", "staged.txt")
    assert path.as_posix().lower() in _listed(main)

    code, lines = _main(capsys, main, "remove", str(path))
    assert (code, lines) == (
        0,
        [f"worktree_removed:{Path(os.path.abspath(path)).as_posix()}"],
    )
    assert not path.exists()
    assert path.as_posix().lower() not in _listed(main)
    assert (main / "base.txt").read_bytes() == b"base\n"


def test_vec_v3_002_a_worktree_without_a_valid_manifest_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-C.11: no manifest, malformed JSON, another kind, no op or another schema: refused."""
    main = _repo(tmp_path)
    good = _manifest("op-1")
    cases: list[tuple[str, bytes | None]] = [
        ("none", None),
        ("malformed", b"{not json"),
        ("executor", json.dumps({**good, "kind": "executor"}).encode("utf-8")),
        (
            "no-op",
            json.dumps({k: v for k, v in good.items() if k != "op"}).encode("utf-8"),
        ),
        (
            "schema",
            json.dumps({**good, "schema": "candidate-worktree/2"}).encode("utf-8"),
        ),
    ]
    for name, data in cases:
        path = _candidate(main, tmp_path, name, data)
        code, lines = _main(capsys, main, "remove", str(path))
        assert (code, lines) == (1, ["worktree_bad:manifest"]), name
        assert path.is_dir(), name
        assert path.as_posix().lower() in _listed(main), name


def test_vec_v3_002_check_land_and_sync_refuse_a_candidate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-C.11: a candidate is never checked, landed or synced as an executor worktree."""
    main = _repo(tmp_path)
    path = _candidate(
        main, tmp_path, "op-1", json.dumps(_manifest("op-1")).encode("utf-8")
    )
    head = _git(main, "rev-parse", "HEAD")
    for argv in (
        ["check", str(path)],
        ["land", str(path)],
        ["sync", str(path), "base.txt"],
    ):
        code, lines = _main(capsys, main, *argv)
        assert (code, lines) == (1, ["worktree_bad:candidate"]), argv
    assert path.is_dir()
    assert _git(main, "rev-parse", "HEAD") == head
    assert (main / "base.txt").read_bytes() == b"base\n"
