"""MEU-939 execution-review corrections R1-F1, R1-F2, R1-F3, R1-F6 (lane part) — red first.

Review: ``.agent/context/handoffs/2026-11-07-standing-commit-grant-implementation-critical-review.md``
Round 1. Threat model: accidents by honest agents, not forgeries.

* R1-F1: ``lanes.py commit`` refuses a pending git operation in the worktree
  (``operation_pending:<marker>`` for MERGE_HEAD, CHERRY_PICK_HEAD, REVERT_HEAD,
  rebase-merge, rebase-apply, sequencer) before git runs, and after the commit
  verifies one parent equal to the prior tip and the bound author and committer
  (D-1: the lane helper makes plain single-parent commits only).
* R1-F2: after the hooks ran, the helper checks the commit as written: its message
  carries no attribution (``commit_fail:verify:attribution``) and its tree is the
  index tree checked before the commit (``commit_fail:verify:tree``). A failed check
  moves the branch back to the prior tip with a compare-and-swap.
* R1-F3: the helper runs the shared secrets scanner (``commit_batch.secret_findings``)
  on the staged blobs itself, so ``SKIP=detect-secrets`` cannot bypass it
  (``secret:<path>``).
* R1-F6: the D-4 main-tree check lists ignored entries too; an ignored entry at a
  landed path refuses ``main_overlap:<path>``, and an ignored entry is never
  ``main_staged``.

The rigs follow ``tools/tests/test_lanes_commit.py`` (real git in ``tmp_path``,
system and global git config cut off, the real ``tools/lanes.py`` CLI). The hooks are
fixture shell scripts switched by flag files; the scanner is a fake detect-secrets
hook named by ``{{PROJECT_NAME_UPPER}}_LANES_SCAN_ENTRY``. Every refusal test asserts the refusal
text and that the lane branch ref is unchanged. Do not skip, only, or early-return
(G36).
"""

from __future__ import annotations

import importlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import pytest

from tools.tests import lane_worktree_config as lwc
from tools.tests import test_lanes_commit as tc

pytestmark = pytest.mark.integration

SLUG = tc.SLUG
NOREPLY = "100+lane@users.noreply.github.com"
SCAN_ENV = "{{PROJECT_NAME_UPPER}}_LANES_SCAN_ENTRY"
CO = "Co-Authored-" + "By: "
TRAILER = CO + "Claude <claude@example.invalid>"
LANE_FILE = f"src/{SLUG}/b.py"
EXTRA_FILE = f"src/{SLUG}/extra.py"
CREDS_FILE = f"src/{SLUG}/creds.py"
SIDE_FILE = "src/side.py"
EMPTY_BASELINE = {
    "version": "1.5.0",
    "plugins_used": [],
    "filters_used": [],
    "results": {},
    "generated_at": "2026-11-02T00:00:00Z",
}
FAKE_SCANNER = r"""
import re
import sys
from pathlib import Path

PATTERN = re.compile(r'PLANTED = "([^"]+)"')
found = []
for rel in sys.argv[1:]:
    path = Path(rel)
    if not path.is_file():
        continue
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if PATTERN.search(line):
            found.append((rel, number))
if found:
    print("ERROR: Potential secrets about to be committed to git repo!")
    for rel, number in found:
        print()
        print("Secret Type: Planted Fixture")
        print(f"Location:    {rel}:{number}")
    sys.exit(1)
sys.exit(0)
"""


def _lanes() -> ModuleType:
    return importlib.import_module("tools.lanes")


@dataclass
class Rig:
    """A ``main`` repository, a ``side`` branch and a linked worktree on ``lane/<SLUG>``."""

    lane: tc.Lane
    hooks: Path
    stage_flag: Path
    trailer_flag: Path
    scan_env: dict[str, str]

    @property
    def wt(self) -> Path:
        return self.lane.wt

    def tip(self) -> str:
        return self.lane.tip()

    def stage(self, rel: str = LANE_FILE, data: bytes = b"B = 1\n") -> None:
        tc._write(self.wt / rel, data)
        tc._git(self.wt, "add", "--", rel)

    def commit(self, **env: str) -> tuple[int, str]:
        proc = tc._commit(self.lane, env={**self.scan_env, **env})
        return proc.returncode, proc.stdout + proc.stderr

    def hook_runs(self) -> int:
        log = self.lane.hook_log
        return log.read_text(encoding="utf-8").count("ran") if log.is_file() else 0


def _pre_commit(log: Path, stage_flag: Path) -> str:
    return (
        "#!/bin/sh\n"
        f'echo ran >> "{log.as_posix()}"\n'
        f'if [ -f "{stage_flag.as_posix()}" ]; then\n'
        f"  mkdir -p src/{SLUG}\n"
        f"  echo 'EXTRA = 1' > {EXTRA_FILE}\n"
        f"  git add -- {EXTRA_FILE}\n"
        "fi\n"
        "exit 0\n"
    )


def _commit_msg(trailer_flag: Path) -> str:
    return (
        "#!/bin/sh\n"
        f'if [ -f "{trailer_flag.as_posix()}" ]; then\n'
        f"  printf '\\n{TRAILER}\\n' >> \"$1\"\n"
        "fi\n"
        "exit 0\n"
    )


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Rig:
    """The ``test_lanes_commit`` repository shape, with a baseline, two hooks and a card.

    ``main`` holds ``.secrets.baseline`` (empty results), so the helper's scan has a
    baseline at the lane tip; ``side`` holds one more commit for merge and cherry-pick
    cases. The worktree's index equals its HEAD; ``Rig.stage`` adds the lane change.
    """
    empty = tmp_path / "empty.gitconfig"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    for var, value in (
        ("GIT_AUTHOR_NAME", "Lane Test"),
        ("GIT_AUTHOR_EMAIL", NOREPLY),
        ("GIT_COMMITTER_NAME", "Lane Test"),
        ("GIT_COMMITTER_EMAIL", NOREPLY),
    ):
        monkeypatch.setenv(var, value)
    monkeypatch.delenv(tc.SESSION_ENV, raising=False)
    monkeypatch.delenv(SCAN_ENV, raising=False)
    main = tmp_path / "repo"
    main.mkdir()
    tc._git(main, "init", "-q", "-b", "main")
    for key, value in (
        ("core.autocrlf", "false"),
        ("user.name", "Lane Test"),
        ("user.email", NOREPLY),
        ("commit.gpgsign", "false"),
    ):
        tc._git(main, "config", key, value)
    tc._write(main / "src" / "a.py", "A = 1\n")
    tc._write(main / lwc.WORKTREE_CONFIG, lwc.WORKTREE_CONFIG_TEXT)
    tc._write(main / ".secrets.baseline", json.dumps(EMPTY_BASELINE, indent=2) + "\n")
    for slug in (tc.SLUG, tc.OTHER_SLUG):
        tc._write(main / tc.PLANS / slug / "task.md", tc._task_text([f"src/{slug}/"]))
    tc._git(main, "add", "-A")
    tc._git(main, "commit", "-q", "--no-verify", "-m", "fixture")
    base = tc._git(main, "rev-parse", "HEAD").strip()
    tc._git(main, "switch", "-q", "-c", "side")
    tc._write(main / "src" / "a.py", "A = 2\n")
    tc._write(main / SIDE_FILE, "SIDE = 1\n")
    tc._git(main, "add", "-A")
    tc._git(main, "commit", "-q", "--no-verify", "-m", "side")
    tc._git(main, "switch", "-q", "main")
    hooks = tmp_path / "hooks"
    hook_log = tmp_path / "hook.log"
    stage_flag = tmp_path / "hook.stage"
    trailer_flag = tmp_path / "hook.trailer"
    for name, text in (
        ("pre-commit", _pre_commit(hook_log, stage_flag)),
        ("commit-msg", _commit_msg(trailer_flag)),
    ):
        tc._write(hooks / name, text)
        (hooks / name).chmod(0o755)
    tc._git(main, "config", "core.hooksPath", hooks.as_posix())
    wt = tmp_path / SLUG
    tc._git(main, "worktree", "add", "-q", "-b", f"lane/{SLUG}", str(wt))
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    message = scratch / "message.txt"
    message.write_bytes(tc.MESSAGE)
    common = Path(
        tc._git(main, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    ).resolve()
    lane = tc.Lane(
        main=main.resolve(),
        wt=wt.resolve(),
        common=common,
        base=base,
        hook_log=hook_log,
        hook_fail=tmp_path / "hook.fail",
        message=message,
        scratch=scratch,
    )
    tc._put_card(lane, tc._card(lane))
    scanner = tmp_path / "scanner" / "fake_hook.py"
    scanner.parent.mkdir(parents=True, exist_ok=True)
    scanner.write_text(FAKE_SCANNER, encoding="utf-8", newline="\n")
    scan_env = {SCAN_ENV: json.dumps([sys.executable, str(scanner), "{paths}"])}
    return Rig(
        lane=lane,
        hooks=hooks,
        stage_flag=stage_flag,
        trailer_flag=trailer_flag,
        scan_env=scan_env,
    )


def _refused(code: int, out: str, reason: str) -> None:
    assert code == 1, (code, out)
    assert any(line.startswith(f"refused: {reason}") for line in out.splitlines()), (
        reason,
        out,
    )
    assert "commit_ok" not in out, out


def _verify_failed(code: int, out: str, kind: str, before: str) -> None:
    assert code == 1, (code, out)
    lines = out.splitlines()
    assert f"commit_fail:{kind}" in lines, (kind, out)
    assert f"lane/{SLUG} stays at {before}" in lines, out
    assert "commit_ok" not in out, out


def _parents(cwd: Path, sha: str) -> list[str]:
    return tc._git(cwd, "rev-list", "--parents", "-n", "1", sha).split()[1:]


# ---------------------------------------------------------------------------
# R1-F1 — a pending git operation refuses before git commit runs
# ---------------------------------------------------------------------------


def test_a_pending_merge_is_operation_pending_and_the_branch_stays(rig: Rig) -> None:
    tc._git(rig.wt, "merge", "--no-commit", "--no-ff", "-q", "side")
    rig.stage()
    before = rig.tip()
    code, out = rig.commit()
    _refused(code, out, "operation_pending:MERGE_HEAD")
    assert rig.tip() == before
    assert rig.hook_runs() == 0, "a refused helper ran the hooks"
    assert (rig.lane.git_dir() / "MERGE_HEAD").is_file(), "the merge state stays"


def test_a_pending_cherry_pick_is_operation_pending_and_the_branch_stays(
    rig: Rig,
) -> None:
    tc._write(rig.wt / "src" / "a.py", "A = 3\n")
    tc._git(rig.wt, "commit", "-q", "--no-verify", "-am", "lane: a 3")
    picked = tc._git_proc(rig.wt, "cherry-pick", "side")
    assert picked.returncode != 0, (picked.stdout, picked.stderr)
    assert (rig.lane.git_dir() / "CHERRY_PICK_HEAD").is_file(), picked.stderr
    tc._write(rig.wt / "src" / "a.py", "A = 4\n")
    tc._git(rig.wt, "add", "-A")
    before = rig.tip()
    code, out = rig.commit()
    _refused(code, out, "operation_pending:CHERRY_PICK_HEAD")
    assert rig.tip() == before
    assert rig.hook_runs() == 0


@pytest.mark.parametrize(
    ("marker", "is_dir"),
    [
        ("REVERT_HEAD", False),
        ("rebase-merge", True),
        ("rebase-apply", True),
        ("sequencer", True),
    ],
)
def test_an_operation_marker_is_operation_pending_and_the_branch_stays(
    rig: Rig, marker: str, is_dir: bool
) -> None:
    rig.stage()
    path = rig.lane.git_dir() / marker
    if is_dir:
        path.mkdir()
    else:
        path.write_text(rig.lane.base + "\n", encoding="utf-8")
    before = rig.tip()
    code, out = rig.commit()
    _refused(code, out, f"operation_pending:{marker}")
    assert rig.tip() == before
    assert rig.hook_runs() == 0


# ---------------------------------------------------------------------------
# R1-F2 — the commit as written is checked after the hooks ran
# ---------------------------------------------------------------------------


def test_a_commit_msg_hook_trailer_is_verify_attribution_and_the_branch_goes_back(
    rig: Rig,
) -> None:
    rig.stage()
    rig.trailer_flag.write_bytes(b"on\n")
    before = rig.tip()
    code, out = rig.commit()
    _verify_failed(code, out, "verify:attribution", before)
    assert rig.tip() == before
    staged = tc._git(rig.wt, "diff", "--cached", "--name-only").split()
    assert staged == [LANE_FILE], "the index keeps the change, as after a soft reset"


def test_a_pre_commit_hook_that_stages_a_file_is_verify_tree_and_the_branch_goes_back(
    rig: Rig,
) -> None:
    rig.stage()
    rig.stage_flag.write_bytes(b"on\n")
    before = rig.tip()
    code, out = rig.commit()
    _verify_failed(code, out, "verify:tree", before)
    assert rig.tip() == before
    assert rig.hook_runs() == 1


# ---------------------------------------------------------------------------
# R1-F3 — the helper's own secrets scan, whatever SKIP says
# ---------------------------------------------------------------------------


def test_a_staged_secret_with_skip_detect_secrets_is_secret_and_the_branch_stays(
    rig: Rig,
) -> None:
    rig.stage()
    rig.stage(CREDS_FILE, b'PLANTED = "fixture-secret-value"\n')
    before = rig.tip()
    code, out = rig.commit(SKIP="detect-secrets")
    _refused(code, out, f"secret:{CREDS_FILE}")
    assert rig.tip() == before
    assert rig.hook_runs() == 0


def test_a_clean_commit_still_commits_once_with_the_bound_identity(rig: Rig) -> None:
    rig.stage()
    rig.stage(f"src/{SLUG}/gone.py", b"GONE = 1\n")
    tc._git(rig.wt, "commit", "-q", "--no-verify", "-m", "lane: gone")
    tc._git(rig.wt, "rm", "-q", "--", f"src/{SLUG}/gone.py")
    before = rig.tip()
    code, out = rig.commit(SKIP="detect-secrets")
    assert code == 0, out
    last = out.strip().splitlines()[-1]
    assert last.startswith("commit_ok:"), out
    sha = last.removeprefix("commit_ok:")
    assert sha == rig.tip()
    assert _parents(rig.wt, sha) == [before]
    shown = tc._git(rig.wt, "show", "-s", "--format=%an|%ae|%cn|%ce", sha).strip()
    assert shown == f"Lane Test|{NOREPLY}|Lane Test|{NOREPLY}", shown
    assert rig.hook_runs() == 1


def test_verify_commit_names_a_merge_commit_and_a_foreign_identity(rig: Rig) -> None:
    """The verifier itself: two parents is ``verify:parents``; another author is ``verify:identity``."""
    lanes = _lanes()
    identity = {
        "GIT_AUTHOR_NAME": "Lane Test",
        "GIT_AUTHOR_EMAIL": NOREPLY,
        "GIT_COMMITTER_NAME": "Lane Test",
        "GIT_COMMITTER_EMAIL": NOREPLY,
    }
    before = rig.tip()
    side = tc._git(rig.wt, "rev-parse", "refs/heads/side").strip()
    tree = tc._git(rig.wt, "rev-parse", f"{before}^{{tree}}").strip()
    merge = tc._git(
        rig.wt, "commit-tree", tree, "-p", before, "-p", side, "-m", "lane: merge"
    ).strip()
    found = lanes._verify_commit(rig.wt, before, merge, identity, tree)
    assert found is not None and found[0] == "verify:parents", found
    other = tc._git_proc(rig.wt, "commit-tree", tree, "-p", before, "-m", "lane: x")
    assert other.returncode == 0, other.stderr
    plain = other.stdout.strip()
    assert lanes._verify_commit(rig.wt, before, plain, identity, tree) is None
    foreign = dict(identity, GIT_AUTHOR_EMAIL="200+other@users.noreply.github.com")
    found = lanes._verify_commit(rig.wt, before, plain, foreign, tree)
    assert found is not None and found[0] == "verify:identity", found


# ---------------------------------------------------------------------------
# R1-F6 — the D-4 main-tree check sees ignored entries
# ---------------------------------------------------------------------------


@dataclass
class MainTree:
    top: Path
    parent: str
    integrated: str


def _main_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> MainTree:
    """``main`` at P (``.gitignore``: ``*.log``, ``build/``); T on ``side`` force-adds ignored paths."""
    empty = tmp_path / "empty.gitconfig"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Lane Test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", NOREPLY)
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Lane Test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", NOREPLY)
    top = tmp_path / "main"
    top.mkdir()
    tc._git(top, "init", "-q", "-b", "main")
    tc._git(top, "config", "core.autocrlf", "false")
    tc._git(top, "config", "commit.gpgsign", "false")
    tc._write(top / ".gitignore", "*.log\nbuild/\ncache/\n")
    tc._write(top / "src" / "a.py", "A = 1\n")
    tc._git(top, "add", "-A")
    tc._git(top, "commit", "-q", "--no-verify", "-m", "P")
    parent = tc._git(top, "rev-parse", "HEAD").strip()
    tc._git(top, "switch", "-q", "-c", "side")
    tc._write(top / "out.log", "landed log\n")
    tc._write(top / "build" / "x.txt", "landed build\n")
    tc._write(top / "src" / "a.py", "A = 2\n")
    tc._git(top, "add", "-f", "--", "out.log", "build/x.txt", "src/a.py")
    tc._git(top, "commit", "-q", "--no-verify", "-m", "T")
    integrated = tc._git(top, "rev-parse", "HEAD").strip()
    tc._git(top, "switch", "-q", "main")
    return MainTree(top=top.resolve(), parent=parent, integrated=integrated)


def _main_ref(tree: MainTree) -> str:
    return tc._git(tree.top, "rev-parse", "refs/heads/main").strip()


@pytest.mark.parametrize(
    ("ignored", "reason"),
    [
        ("out.log", "main_overlap:out.log"),
        ("build/local.txt", "main_overlap:build"),
    ],
)
def test_an_ignored_entry_at_a_landed_path_is_main_overlap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ignored: str, reason: str
) -> None:
    lanes = _lanes()
    tree = _main_tree(tmp_path, monkeypatch)
    tc._write(tree.top / ignored, "local ignored bytes\n")
    before = _main_ref(tree)
    with pytest.raises(lanes.Refusal) as caught:
        lanes._check_main_dirt(tree.top, tree.parent, tree.integrated, None)
    assert caught.value.reason == reason, caught.value
    assert _main_ref(tree) == before
    assert (tree.top / ignored).read_bytes() == b"local ignored bytes\n"


def test_an_ignored_entry_off_the_landed_paths_is_neither_staged_nor_overlap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lanes = _lanes()
    tree = _main_tree(tmp_path, monkeypatch)
    tc._write(tree.top / "notes.log", "local\n")
    tc._write(tree.top / "cache" / "big.bin", "local\n")
    before = _main_ref(tree)
    lanes._check_main_dirt(tree.top, tree.parent, tree.integrated, None)
    assert _main_ref(tree) == before
