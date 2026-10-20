from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from tools.tests.run_parameters_fixtures import phase_b3 as b3


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".agent/skills/git-workflow/scripts/agent-commit.ps1"
TARGET = b"approved target\n"
RELEASE = "release: exact signed scope\n"
SIGNER = {"name": "Test Signer", "email": "signer@example.com"}
# The originating repo routes commands through its output proxy (``rtk proxy``); an adopter
# without one runs them directly.
PROXY = ["rtk", "proxy"] if shutil.which("rtk") else []


def _run(
    *args: str, cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*PROXY, *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _must_run(*args: str, cwd: Path, env: dict[str, str] | None = None) -> str:
    completed = _run(*args, cwd=cwd, env=env)
    assert completed.returncode == 0, (
        f"command failed: {args}\n{completed.stdout}\n{completed.stderr}"
    )
    return completed.stdout.strip()


def _tree_for_scope(repo: Path, scope: str, index: Path) -> str:
    env = os.environ.copy()
    env["GIT_INDEX_FILE"] = str(index)
    _must_run("git", "read-tree", "HEAD", cwd=repo, env=env)
    _must_run("git", "add", "--", scope, cwd=repo, env=env)
    return _must_run("git", "write-tree", cwd=repo, env=env)


def _fixture(tmp_path: Path, message: str) -> dict[str, Any]:
    """A signed B-3 rig whose op ``op-agent`` stopped at ``blobs_stored:done`` (AC-C.5, AC-C.7).

    The exact-scope parameters name the op's packet; ``env`` carries the grant, so the script
    runs the candidate, publish and index phases of that op.
    """
    text = SCRIPT.read_text(encoding="utf-8")
    for token in (
        "RepositoryPath",
        "ScopeManifest",
        "ExpectedBase",
        "ExpectedTree",
        "ContentDescriptor",
        "MessageFile",
        "OutputState",
    ):
        assert token in text, message

    rig = b3.rig(tmp_path / "fx", ROOT)
    repo = rig.repo
    (repo / "target.txt").write_bytes(TARGET)
    (repo / "unrelated.txt").write_bytes(b"unrelated staged\n")
    rig.git("add", "--", "unrelated.txt")

    manifest = tmp_path / "scope.txt"
    manifest.write_bytes(b"target.txt\n")
    message_file = tmp_path / "message.txt"
    message_file.write_bytes(RELEASE.encode("utf-8"))
    base = rig.ref()
    tree = _tree_for_scope(repo, "target.txt", tmp_path / "isolated-index")
    descriptor = tmp_path / "descriptor.json"
    descriptor.write_bytes(
        (
            json.dumps(
                {
                    "parent": base,
                    "tree": tree,
                    "message_sha256": hashlib.sha256(
                        message_file.read_bytes()
                    ).hexdigest(),
                    "author_name": SIGNER["name"],
                    "author_email": SIGNER["email"],
                    "signing_fingerprint": rig.fingerprint,
                }
            )
            + "\n"
        ).encode("utf-8")
    )

    op = "op-agent"
    rig.reserve(op)
    packet = rig.packet(files={"target.txt": TARGET}, author=SIGNER, message=RELEASE)
    rig.crash(op, packet, "blobs_stored:done")
    return {
        "repo": repo,
        "manifest": manifest,
        "message": message_file,
        "base": base,
        "tree": tree,
        "descriptor": descriptor,
        "state": tmp_path / "state.json",
        "op": op,
        "rig": rig,
        "packet": packet,
        "env": rig.fx.env(**{"{{PROJECT_NAME_UPPER}}_COMMIT_GRANT": op, "{{PROJECT_NAME_UPPER}}_PYTHON": sys.executable}),
    }


def _invoke(
    values: dict[str, Any],
    *extra: str,
    env: dict[str, str] | None = None,
    no_push: bool = True,
) -> subprocess.CompletedProcess[str]:
    """The exact-scope parameters of ``values``, then ``extra``; ``env`` replaces the grant env."""
    return _run(
        "pwsh",
        "-NoProfile",
        "-File",
        str(SCRIPT),
        "-RepositoryPath",
        str(values["repo"]),
        "-ScopeManifest",
        str(values["manifest"]),
        "-ExpectedBase",
        str(values["base"]),
        "-ExpectedTree",
        str(values["tree"]),
        "-ContentDescriptor",
        str(values["descriptor"]),
        "-MessageFile",
        str(values["message"]),
        "-OutputState",
        str(values["state"]),
        "-SkipTests",
        *(["-NoPush"] if no_push else []),
        *extra,
        cwd=Path(values["repo"]),
        env=values["env"] if env is None else env,
    )


def _reason(completed: subprocess.CompletedProcess[str]) -> str | None:
    """The ``reason`` of the script's last JSON stdout line (EA-8 (j))."""
    return b3.last_json(completed.stdout).get("reason")


def _legacy_repo(tmp_path: Path) -> Path:
    """A plain repository with a staged change, for the default (non-exact) mode."""
    repo = tmp_path / "legacy"
    repo.mkdir()
    _must_run("git", "init", "-b", "main", cwd=repo)
    _must_run("git", "config", "user.name", "Test Signer", cwd=repo)
    _must_run("git", "config", "user.email", "signer@example.com", cwd=repo)
    (repo / "base.txt").write_bytes(b"base\n")
    _must_run("git", "add", "base.txt", cwd=repo)
    _must_run("git", "-c", "commit.gpgsign=false", "commit", "-m", "base", cwd=repo)
    (repo / "change.txt").write_bytes(b"change\n")
    _must_run("git", "add", "change.txt", cwd=repo)
    return repo


def test_creates_signed_commit_matching_packet_content(tmp_path: Path) -> None:
    message = "signed commit did not match packet-bound content"
    values = _fixture(tmp_path, message)
    completed = _invoke(values)
    assert completed.returncode == 0, (
        f"{message}\n{completed.stdout}\n{completed.stderr}"
    )
    repo = Path(values["repo"])
    actual = _must_run("git", "rev-parse", "HEAD", cwd=repo)
    assert _must_run("git", "rev-parse", "HEAD^", cwd=repo) == values["base"], message
    assert (
        _must_run("git", "show", "-s", "--format=%T", "HEAD", cwd=repo)
        == values["tree"]
    ), message
    assert _run("git", "verify-commit", actual, cwd=repo).returncode == 0, message
    assert "BEGIN SSH SIGNATURE" in _must_run(
        "git", "cat-file", "-p", actual, cwd=repo
    ), message
    state = json.loads(Path(values["state"]).read_text(encoding="utf-8-sig"))
    assert state["actual_sha"] == actual and state["tree"] == values["tree"], message


def test_exact_scope_preserves_unrelated_index_entries(tmp_path: Path) -> None:
    message = "exact-scope commit changed unrelated index entries"
    values = _fixture(tmp_path, message)
    repo = Path(values["repo"])
    before = _must_run("git", "show", ":unrelated.txt", cwd=repo)
    completed = _invoke(values)
    assert completed.returncode == 0, (
        f"{message}\n{completed.stdout}\n{completed.stderr}"
    )
    after = _must_run("git", "show", ":unrelated.txt", cwd=repo)
    assert after == before == "unrelated staged", message


def test_exact_scope_refuses_without_canonical_op(tmp_path: Path) -> None:
    """AC-C.5: exact-scope parameters with no grant name no reservation: ``grant``, no write."""
    message = "exact-scope commit ran without a canonical op"
    values = _fixture(tmp_path, message)
    rig: b3.Rig = values["rig"]
    index = rig.index()
    env = rig.fx.env(**{"{{PROJECT_NAME_UPPER}}_COMMIT_GRANT": None, "{{PROJECT_NAME_UPPER}}_PYTHON": sys.executable})
    completed = _invoke(values, env=env)
    assert completed.returncode != 0, (
        f"{message}\n{completed.stdout}\n{completed.stderr}"
    )
    assert _reason(completed) == "grant", completed.stdout
    assert rig.ref() == values["base"]
    assert rig.index() == index
    assert rig.journal(values["op"])[-1] == ("blobs_stored", "done")


def test_exact_scope_phases_run_in_order_then_the_driver_reconciles(
    tmp_path: Path,
) -> None:
    """AC-C.7: ``-Phase`` runs one op phase; a phase whose predecessor is not done is refused."""
    message = "exact-scope phases did not follow the op journal"
    values = _fixture(tmp_path, message)
    rig: b3.Rig = values["rig"]
    base = values["base"]

    early = _invoke(values, "-Phase", "publish")
    assert (early.returncode, _reason(early)) == (1, "phase_order"), early.stdout
    assert rig.ref() == base

    for phase in ("candidate", "publish", "index"):
        completed = _invoke(values, "-Phase", phase)
        assert completed.returncode == 0, (
            f"{phase}\n{completed.stdout}\n{completed.stderr}"
        )
        assert b3.last_json(completed.stdout).get("phase") == phase, completed.stdout
    tip = rig.ref()
    assert rig.parents(tip) == [base]
    assert ("index_reconciled", "done") in rig.journal(values["op"])

    code, out, text = rig.commit(values["op"], values["packet"])
    assert (code, out.get("result"), out.get("commit")) == (0, "reconciled", tip), text
    assert rig.journal(values["op"])[-1] == ("reconciled", "done")


def test_exact_scope_publish_refuses_a_moved_ref(tmp_path: Path) -> None:
    """AC-C.7: a ref that moved after the candidate phase refuses the publish with a journal."""
    message = "exact-scope publish ignored a moved ref"
    values = _fixture(tmp_path, message)
    rig: b3.Rig = values["rig"]
    base = values["base"]
    candidate = _invoke(values, "-Phase", "candidate")
    assert candidate.returncode == 0, f"{candidate.stdout}\n{candidate.stderr}"
    other = rig.other_commit(base, "moved")
    rig.git("update-ref", "refs/heads/main", other, base)

    publish = _invoke(values, "-Phase", "publish")
    assert (publish.returncode, _reason(publish)) == (1, "publish_refused"), (
        publish.stdout
    )
    assert rig.ref() == other
    journal = rig.journal(values["op"])
    assert ("candidate_verified", "done") in journal
    assert ("published", "done") not in journal


def test_exact_scope_parameters_must_match_the_op(tmp_path: Path) -> None:
    """AC-C.5: exact parameters that differ from the granted op's packet: ``packet_mismatch``."""
    message = "exact-scope parameters were not bound to the op"
    values = _fixture(tmp_path, message)
    rig: b3.Rig = values["rig"]
    wrong = rig.git("rev-parse", f"{values['base']}^{{tree}}")
    completed = _invoke({**values, "tree": wrong})
    assert (completed.returncode, _reason(completed)) == (1, "packet_mismatch"), (
        completed.stdout
    )
    assert rig.ref() == values["base"]


def test_exact_scope_requires_no_push(tmp_path: Path) -> None:
    """AC-C.7: exact-scope mode never pushes; without ``-NoPush`` it refuses before a write."""
    message = "exact-scope mode ran without -NoPush"
    values = _fixture(tmp_path, message)
    rig: b3.Rig = values["rig"]
    completed = _invoke(values, no_push=False)
    assert completed.returncode != 0, completed.stdout
    assert rig.ref() == values["base"]


def test_default_mode_refuses_a_missing_message_and_attribution(tmp_path: Path) -> None:
    """AC-C.7: the default mode still needs ``-Message`` and refuses an AI attribution (D-5)."""
    repo = _legacy_repo(tmp_path)
    head = _must_run("git", "rev-parse", "HEAD", cwd=repo)
    trailer = "Co-Authored-" + "By: Claude <noreply@anthropic.com>"
    for args in (
        ["-NoPush", "-SkipTests"],
        ["-Message", "feat: legacy", "-Body", trailer, "-NoPush", "-SkipTests"],
    ):
        completed = _run("pwsh", "-NoProfile", "-File", str(SCRIPT), *args, cwd=repo)
        assert completed.returncode == 1, (args, completed.stdout, completed.stderr)
        assert _must_run("git", "rev-parse", "HEAD", cwd=repo) == head, args
