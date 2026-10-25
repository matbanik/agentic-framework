"""MEU-785 AC-785.2–.5, .7, .8, .10: lane commit helper, claim and release — red first (G19).

FIC: ``docs/execution/plans/2026-10-22-lane-branches-governed-land/implementation-plan.md``
AC-785.2 (D:274), AC-785.3 and AC-785.4 (D:171-176, D:281), AC-785.5 (D:175),
AC-785.7 (D:170, D:274), AC-785.8 (D:217, D:252) and AC-785.10 (brief B:215-219).

CLI contract (stage 1, EA-8 of MEU-784, unchanged): a refusal prints
``refused: <reason>`` on stdout and exits 1. The helper is
``lanes.py commit --worktree W --message-file F``; it takes the worktree lease
(``<git dir of W>/{{PROJECT_NAME}}-gate.lock``), checks the card under the registry lock,
checks that HEAD is the symbolic ref ``refs/heads/lane/<slug>``, runs
``git commit -F F`` with a fixed argv, the hooks and a cleaned environment, and
prints ``commit_ok:<sha>``. The WARN line of a refusal has no fixed format in the
plan, so these tests pin the reason token and the absence of every write.

Every repository is disposable, in ``tmp_path``, with system and global git config
cut off. The worktree folder, the plan folder and the branch suffix share one slug,
so every reading of ``lane/<slug>`` names the same branch. The pre-commit hook is a
fixture shell script that logs each run and fails while a flag file exists. Lock
holders are separate processes with this file's own copy of the lock protocol
(from ``test_lanes.py``, copied, not imported). Tests reach new symbols at run
time. Do not skip, only, or early-return (G36).
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from tools.tests import lane_worktree_config as lwc

ROOT = Path(__file__).resolve().parents[2]
LANES = ROOT / "tools" / "lanes.py"
PLANS = "docs/execution/plans"
SLUG = "2026-10-20-lane-a"
OTHER_SLUG = "2026-10-20-lane-b"
SESSION = "s-one"
GENERATION = "0123456789abcdef"
OP_ID = "op-lane-a-1"
WAIT_S = 0.2
POLL_S = 0.01
CLI_TIMEOUT_S = 120
GATE_LOCK = "{{PROJECT_NAME}}-gate.lock"
SESSION_ENV = "{{PROJECT_NAME_UPPER}}_SESSION"
MESSAGE = b"lane: add b\n\nThe lane commit helper test.\n"
MESSAGE_MAX = 64 * 1024
POISON_KEYS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_CONFIG_PARAMETERS",
    "GIT_CONFIG_COUNT",
    "GIT_CONFIG_KEY_0",
    "GIT_CONFIG_VALUE_0",
)
FORBIDDEN_ARGS = ("--no-verify", "-n", "-c")

HOLDER = """
import os
import sys

path, body = sys.argv[1], sys.argv[2]
flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOINHERIT", 0)
fd = os.open(path, flags, 0o644)
try:
    if sys.platform == "win32":
        import msvcrt
        os.lseek(fd, 2**20, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except OSError:
    print("busy", flush=True)
    sys.exit(1)
os.ftruncate(fd, 0)
os.lseek(fd, 0, os.SEEK_SET)
os.write(fd, body.replace("{pid}", str(os.getpid())).encode("utf-8"))
print(f"held {os.getpid()}", flush=True)
sys.stdin.read()
if sys.platform == "win32":
    os.lseek(fd, 2**20, os.SEEK_SET)
    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
else:
    fcntl.flock(fd, fcntl.LOCK_UN)
os.close(fd)
"""
HOLDER_BODY = '{"pid": {pid}, "argv": ["holder.py", "gate"]}'


def _lanes() -> ModuleType:
    return importlib.import_module("tools.lanes")


def _clean_env() -> dict[str, str]:
    """``os.environ`` without the poison keys, for the test's own git calls."""
    return {
        key: value
        for key, value in os.environ.items()
        if key not in POISON_KEYS
        and not key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))
    }


def _git_proc(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_clean_env(),
        check=False,
    )


def _git(cwd: Path, *args: str) -> str:
    proc = _git_proc(cwd, *args)
    assert proc.returncode == 0, (args, proc.stdout, proc.stderr)
    return proc.stdout


def _write(path: Path, data: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)


def _task_text(owns: list[str]) -> str:
    return (
        "---\nproject: fixture\n---\n\n# Task\n\n| # | Task |\n|---|---|\n| 1 | work |\n"
        "\n## Lane Ownership\n\n```yaml\nowns:\n"
        + "".join(f"  - {item}\n" for item in owns)
        + "must_not_touch: []\n```\n"
    )


def _hook_text(log: Path, flag: Path) -> str:
    return (
        "#!/bin/sh\n"
        f'echo ran >> "{log.as_posix()}"\n'
        f'if [ -f "{flag.as_posix()}" ]; then exit 1; fi\n'
        "exit 0\n"
    )


@dataclass
class Lane:
    main: Path
    wt: Path
    common: Path
    base: str
    hook_log: Path
    hook_fail: Path
    message: Path
    scratch: Path

    @property
    def lanes_dir(self) -> Path:
        return self.common / "lanes"

    @property
    def card_path(self) -> Path:
        return self.lanes_dir / f"{SLUG}.json"

    @property
    def branch(self) -> str:
        return f"lane/{SLUG}"

    @property
    def branch_ref(self) -> str:
        return f"refs/heads/lane/{SLUG}"

    def git_dir(self, wt: Path | None = None) -> Path:
        return Path(
            _git(wt or self.wt, "rev-parse", "--absolute-git-dir").strip()
        ).resolve()

    def tip(self) -> str:
        return _git(self.main, "rev-parse", self.branch_ref).strip()


@pytest.fixture
def lane(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Lane:
    """One repository on ``main`` and one linked worktree on ``lane/<SLUG>``.

    The worktree holds one staged change and a valid message file, so a helper
    call has something to commit.
    """
    empty = tmp_path / "empty.gitconfig"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    for var, value in (
        ("GIT_AUTHOR_NAME", "Lane Test"),
        ("GIT_AUTHOR_EMAIL", "lane@example.invalid"),
        ("GIT_COMMITTER_NAME", "Lane Test"),
        ("GIT_COMMITTER_EMAIL", "lane@example.invalid"),
    ):
        monkeypatch.setenv(var, value)
    monkeypatch.delenv(SESSION_ENV, raising=False)
    main = tmp_path / "repo"
    main.mkdir()
    _git(main, "init", "-q", "-b", "main")
    for key, value in (
        ("core.autocrlf", "false"),
        ("user.name", "Lane Test"),
        ("user.email", "lane@example.invalid"),
        ("commit.gpgsign", "false"),
    ):
        _git(main, "config", key, value)
    _write(main / "src" / "a.py", "A = 1\n")
    _write(main / lwc.WORKTREE_CONFIG, lwc.WORKTREE_CONFIG_TEXT)
    for slug in (SLUG, OTHER_SLUG):
        _write(main / PLANS / slug / "task.md", _task_text([f"src/{slug}/"]))
    _git(main, "add", "-A")
    _git(main, "commit", "-q", "-m", "fixture")
    base = _git(main, "rev-parse", "HEAD").strip()
    hooks = tmp_path / "hooks"
    hook_log = tmp_path / "hook.log"
    hook_fail = tmp_path / "hook.fail"
    hook = hooks / "pre-commit"
    _write(hook, _hook_text(hook_log, hook_fail))
    hook.chmod(0o755)
    _git(main, "config", "core.hooksPath", hooks.as_posix())
    wt = tmp_path / SLUG
    _git(main, "worktree", "add", "-q", "-b", f"lane/{SLUG}", str(wt))
    _write(wt / "src" / SLUG / "b.py", "B = 1\n")
    _git(wt, "add", "-A")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    message = scratch / "message.txt"
    message.write_bytes(MESSAGE)
    common = Path(
        _git(main, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    ).resolve()
    return Lane(
        main=main.resolve(),
        wt=wt.resolve(),
        common=common,
        base=base,
        hook_log=hook_log,
        hook_fail=hook_fail,
        message=message,
        scratch=scratch,
    )


def _run(
    cwd: Path, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    full_env = _clean_env()
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, str(LANES), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=full_env,
        timeout=CLI_TIMEOUT_S,
        check=False,
    )


def _claim(lane: Lane, wt: Path, slug: str = SLUG) -> subprocess.CompletedProcess[str]:
    return _run(
        wt,
        "claim",
        "--plan",
        f"{PLANS}/{slug}",
        "--worktree",
        str(wt),
        "--session",
        SESSION,
    )


def _commit(
    lane: Lane,
    *,
    message: Path | None = None,
    session: str = SESSION,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    full = {SESSION_ENV: session}
    if env:
        full.update(env)
    return _run(
        lane.wt,
        "commit",
        "--worktree",
        str(lane.wt),
        "--message-file",
        str(message or lane.message),
        env=full,
    )


def _release(lane: Lane) -> subprocess.CompletedProcess[str]:
    """``release --worktree W`` (boundary row IP:143); the session comes from the env."""
    return _run(
        lane.main,
        "release",
        "--worktree",
        str(lane.wt),
        env={SESSION_ENV: SESSION},
    )


def _ok(proc: subprocess.CompletedProcess[str]) -> str:
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
    return proc.stdout


def _refused(proc: subprocess.CompletedProcess[str], reason: str) -> str:
    assert proc.returncode == 1, (proc.returncode, proc.stdout, proc.stderr)
    lines = proc.stdout.splitlines()
    assert any(line.startswith(f"refused: {reason}") for line in lines), (
        reason,
        proc.stdout,
        proc.stderr,
    )
    return proc.stdout


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _card(lane: Lane, /, **over: Any) -> dict[str, Any]:
    # Positional-only, so a case can override the ``lane`` field by keyword.
    card: dict[str, Any] = {
        "lane": SLUG,
        "generation": GENERATION,
        "session": SESSION,
        "state": "active",
        "op": None,
        "worktree": lane.wt.as_posix(),
        "branch": lane.branch,
        "plan": f"{PLANS}/{SLUG}/",
        "owns": [f"src/{SLUG}/"],
        "claims": [],
        "gates": [],
        "updated": _utc_now(),
    }
    card.update(over)
    return card


def _put_card(lane: Lane, card: dict[str, Any]) -> Path:
    lane.lanes_dir.mkdir(parents=True, exist_ok=True)
    path = lane.lanes_dir / f"{card['lane']}.json"
    path.write_text(json.dumps(card), encoding="utf-8")
    return path


class _Holder:
    """A separate process that holds the lock on ``path`` until ``stop``."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.proc = subprocess.Popen(
            [sys.executable, "-c", HOLDER, str(path), HOLDER_BODY],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert self.proc.stdout is not None
        line = self.proc.stdout.readline().strip()
        word, _, pid = line.partition(" ")
        assert word == "held" and pid.isdigit(), line

    def stop(self) -> None:
        if self.proc.poll() is None:
            assert self.proc.stdin is not None
            self.proc.stdin.close()
            self.proc.wait(timeout=30)


def _state(lane: Lane) -> dict[str, bytes | str | None]:
    """The lane ref, the index bytes, HEAD and every card's bytes."""
    index = lane.git_dir() / "index"
    cards = sorted(lane.lanes_dir.glob("*.json")) if lane.lanes_dir.is_dir() else []
    state: dict[str, bytes | str | None] = {
        "ref": lane.tip(),
        "index": index.read_bytes() if index.is_file() else None,
        "head": (lane.git_dir() / "HEAD").read_text(encoding="utf-8"),
    }
    for path in cards:
        state[f"card:{path.name}"] = path.read_bytes()
    return state


def _shows_path(proc: subprocess.CompletedProcess[str], token: str, path: Path) -> bool:
    for line in proc.stdout.splitlines():
        if line.startswith(f"{token}:"):
            shown = Path(line[len(token) + 1 :].strip())
            if shown.exists() and os.path.samefile(shown, path):
                return True
    return False


# ---------------------------------------------------------------------------
# AC-785.2 — no linked worktree has main checked out
# ---------------------------------------------------------------------------


def test_lanes_check_reports_a_linked_worktree_on_main(lane: Lane) -> None:
    on_main = lane.scratch.parent / "on-main"
    _git(lane.main, "worktree", "add", "-q", "--force", str(on_main), "main")
    proc = _run(on_main, "check", "--plan", f"{PLANS}/{SLUG}")
    assert proc.returncode == 1, (proc.returncode, proc.stdout, proc.stderr)
    assert _shows_path(proc, "main_reserved", on_main), (proc.stdout, proc.stderr)


# ---------------------------------------------------------------------------
# AC-785.7 — claim records the branch; main tree and non-lane HEADs refused
# ---------------------------------------------------------------------------


def test_claim_records_the_lane_branch_from_the_symbolic_head(lane: Lane) -> None:
    _ok(_claim(lane, lane.wt))
    card = json.loads(lane.card_path.read_text(encoding="utf-8"))
    assert card["branch"] == lane.branch, card


def test_claim_from_the_main_tree_is_main_reserved_and_writes_no_card(
    lane: Lane,
) -> None:
    _refused(_claim(lane, lane.main), "main_reserved")
    assert not lane.card_path.exists()


def test_claim_on_a_detached_head_is_head_not_lane(lane: Lane) -> None:
    detached = lane.scratch.parent / "detached"
    _git(lane.main, "worktree", "add", "-q", "--detach", str(detached))
    _refused(_claim(lane, detached.resolve()), "head_not_lane")
    assert not lane.card_path.exists()


def test_claim_on_a_non_lane_branch_is_head_not_lane(lane: Lane) -> None:
    feature = lane.scratch.parent / "feature"
    _git(lane.main, "worktree", "add", "-q", "-b", "feature", str(feature))
    _refused(_claim(lane, feature.resolve()), "head_not_lane")
    assert not lane.card_path.exists()


# ---------------------------------------------------------------------------
# AC-785.3 — the helper commits on the lane branch through the hooks
# ---------------------------------------------------------------------------


def test_the_helper_commits_on_the_lane_branch_with_the_hooks(lane: Lane) -> None:
    _ok(_claim(lane, lane.wt))
    proc = _commit(lane)
    out = _ok(proc)
    last = out.strip().splitlines()[-1]
    assert last.startswith("commit_ok:"), out
    sha = last.removeprefix("commit_ok:")
    assert sha == lane.tip(), (sha, lane.tip())
    assert _git(lane.main, "rev-parse", f"{sha}^").strip() == lane.base
    body = _git(lane.main, "cat-file", "commit", sha).split("\n\n", 1)[1]
    assert body.encode("utf-8") == MESSAGE, body
    assert _git(lane.wt, "symbolic-ref", "HEAD").strip() == lane.branch_ref
    assert _git(lane.main, "rev-parse", "refs/heads/main").strip() == lane.base
    assert lane.hook_log.read_text(encoding="utf-8").count("ran") == 1


def test_a_failing_hook_is_commit_fail_hook_and_the_branch_stays(lane: Lane) -> None:
    _ok(_claim(lane, lane.wt))
    lane.hook_fail.write_bytes(b"fail\n")
    proc = _commit(lane)
    assert proc.returncode != 0, (proc.stdout, proc.stderr)
    assert "commit_fail:hook" in proc.stdout, (proc.stdout, proc.stderr)
    assert "commit_ok" not in proc.stdout
    assert lane.tip() == lane.base
    assert lane.hook_log.read_text(encoding="utf-8").count("ran") == 1


# ---------------------------------------------------------------------------
# AC-785.4 — one test per refusal, each with no write
# ---------------------------------------------------------------------------


def _setup_card_superseded(lane: Lane) -> dict[str, str]:
    _put_card(lane, _card(lane, state="released"))
    return {}


def _setup_session_mismatch(lane: Lane) -> dict[str, str]:
    _put_card(lane, _card(lane))
    return {SESSION_ENV: "s-two"}


def _setup_worktree_mismatch(lane: Lane) -> dict[str, str]:
    other = lane.scratch.parent / OTHER_SLUG
    _git(lane.main, "worktree", "add", "-q", "-b", f"lane/{OTHER_SLUG}", str(other))
    _put_card(
        lane,
        _card(
            lane,
            lane=OTHER_SLUG,
            worktree=other.resolve().as_posix(),
            branch=f"lane/{OTHER_SLUG}",
            plan=f"{PLANS}/{OTHER_SLUG}/",
            owns=[f"src/{OTHER_SLUG}/"],
        ),
    )
    return {}


def _setup_branch_mismatch(lane: Lane) -> dict[str, str]:
    _put_card(lane, _card(lane, branch=f"lane/{OTHER_SLUG}"))
    return {}


def _setup_card_landing(lane: Lane) -> dict[str, str]:
    _put_card(lane, _card(lane, state="landing", op=OP_ID))
    return {}


def _setup_head_not_lane(lane: Lane) -> dict[str, str]:
    _put_card(lane, _card(lane))
    _git(lane.wt, "checkout", "-q", "--detach")
    return {}


def _setup_halt(lane: Lane) -> dict[str, str]:
    _put_card(lane, _card(lane))
    (lane.lanes_dir / "HALT").write_bytes(b"")
    return {}


REFUSALS: dict[str, Callable[[Lane], dict[str, str]]] = {
    "card_superseded": _setup_card_superseded,
    "session_mismatch": _setup_session_mismatch,
    "worktree_mismatch": _setup_worktree_mismatch,
    "branch_mismatch": _setup_branch_mismatch,
    "card_landing": _setup_card_landing,
    "head_not_lane": _setup_head_not_lane,
}


@pytest.mark.parametrize("reason", sorted(REFUSALS))
def test_the_helper_refuses_without_a_write(lane: Lane, reason: str) -> None:
    env = REFUSALS[reason](lane)
    before = _state(lane)
    proc = _commit(lane, env=env)
    _refused(proc, reason)
    assert "commit_ok" not in proc.stdout
    assert _state(lane) == before
    assert not lane.hook_log.exists(), "a refused helper ran the hooks"


def test_the_helper_is_lease_busy_while_the_worktree_lease_is_held(lane: Lane) -> None:
    _put_card(lane, _card(lane))
    holder = _Holder(lane.git_dir() / GATE_LOCK)
    try:
        before = _state(lane)
        proc = _commit(lane)
        after = _state(lane)
    finally:
        holder.stop()
    _refused(proc, "lease_busy")
    assert "commit_ok" not in proc.stdout
    assert after == before
    assert not lane.hook_log.exists()


def test_the_helper_stops_under_halt_without_a_write(lane: Lane) -> None:
    _setup_halt(lane)
    before = _state(lane)
    proc = _commit(lane)
    assert proc.returncode != 0, (proc.stdout, proc.stderr)
    assert any("halt" in line for line in proc.stdout.splitlines()), proc.stdout
    assert "commit_ok" not in proc.stdout
    assert _state(lane) == before
    assert not lane.hook_log.exists()


MESSAGE_FILES: dict[str, bytes | None] = {
    "missing": None,
    "empty": b"",
    "too_large": b"x" * (MESSAGE_MAX + 1),
    "nul": b"lane: bad\0message\n",
    "not_utf8": b"lane: \xff\xfe bad\n",
}


@pytest.mark.parametrize("case", sorted(MESSAGE_FILES))
def test_the_helper_refuses_a_bad_message_file(lane: Lane, case: str) -> None:
    _put_card(lane, _card(lane))
    message = lane.scratch / f"{case}.txt"
    data = MESSAGE_FILES[case]
    if data is not None:
        message.write_bytes(data)
    before = _state(lane)
    proc = _commit(lane, message=message)
    _refused(proc, "message_file")
    assert "commit_ok" not in proc.stdout
    assert _state(lane) == before
    assert not lane.hook_log.exists()


def test_a_message_file_of_exactly_64_kib_commits(lane: Lane) -> None:
    _put_card(lane, _card(lane))
    message = lane.scratch / "limit.txt"
    message.write_bytes(
        b"lane: limit\n\n" + b"y" * (MESSAGE_MAX - len(b"lane: limit\n\n"))
    )
    proc = _commit(lane, message=message)
    out = _ok(proc)
    assert out.strip().splitlines()[-1] == f"commit_ok:{lane.tip()}"


# ---------------------------------------------------------------------------
# AC-785.5 — the child env and argv are cleaned
# ---------------------------------------------------------------------------


def _decoy(lane: Lane) -> Path:
    decoy = lane.scratch.parent / "decoy"
    decoy.mkdir()
    _git(decoy, "init", "-q", "-b", "main")
    _git(decoy, "config", "user.name", "Decoy")
    _git(decoy, "config", "user.email", "decoy@example.invalid")
    _write(decoy / "d.txt", "decoy\n")
    _git(decoy, "add", "-A")
    _git(decoy, "commit", "-q", "--no-verify", "-m", "decoy")
    return decoy


def _poison(decoy: Path, hooks: Path) -> dict[str, str]:
    return {
        "GIT_DIR": str(decoy / ".git"),
        "GIT_WORK_TREE": str(decoy),
        "GIT_INDEX_FILE": str(decoy / ".git" / "index"),
        "GIT_CONFIG_PARAMETERS": f"'core.hooksPath'='{hooks.as_posix()}'",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "core.hooksPath",
        "GIT_CONFIG_VALUE_0": hooks.as_posix(),
    }


def test_a_poisoned_git_env_cannot_move_the_commit_off_the_lane(lane: Lane) -> None:
    _put_card(lane, _card(lane))
    decoy = _decoy(lane)
    no_hooks = lane.scratch / "no-hooks"
    no_hooks.mkdir()
    decoy_head = _git(decoy, "rev-parse", "HEAD").strip()
    decoy_index = (decoy / ".git" / "index").read_bytes()
    proc = _commit(lane, env=_poison(decoy, no_hooks))
    out = _ok(proc)
    assert out.strip().splitlines()[-1] == f"commit_ok:{lane.tip()}"
    assert lane.tip() != lane.base
    assert _git(decoy, "rev-parse", "HEAD").strip() == decoy_head
    assert (decoy / ".git" / "index").read_bytes() == decoy_index
    assert lane.hook_log.read_text(encoding="utf-8").count("ran") == 1, (
        "the poisoned hooksPath replaced the repository hooks"
    )


def test_the_helper_commit_argv_and_env_are_fixed_and_clean(
    lane: Lane, monkeypatch: pytest.MonkeyPatch
) -> None:
    _put_card(lane, _card(lane))
    decoy = _decoy(lane)
    no_hooks = lane.scratch / "no-hooks"
    no_hooks.mkdir()
    lanes = _lanes()
    calls: list[tuple[list[str], dict[str, str] | None]] = []
    real_popen = subprocess.Popen

    class Recording(real_popen):  # type: ignore[valid-type, misc]  # records, then runs
        def __init__(self, args: Any, *rest: Any, **kwargs: Any) -> None:
            argv = [str(item) for item in args] if not isinstance(args, str) else [args]
            env = kwargs.get("env")
            calls.append((argv, dict(env) if env is not None else None))
            super().__init__(args, *rest, **kwargs)

    for key, value in _poison(decoy, no_hooks).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv(SESSION_ENV, SESSION)
    monkeypatch.chdir(lane.wt)
    monkeypatch.setattr(subprocess, "Popen", Recording)
    code = lanes.main(
        ["commit", "--worktree", str(lane.wt), "--message-file", str(lane.message)],
        wait_s=WAIT_S,
        poll_s=POLL_S,
    )
    monkeypatch.setattr(subprocess, "Popen", real_popen)
    commits = [
        (argv, env)
        for argv, env in calls
        if argv and Path(argv[0]).stem.lower() == "git" and "commit" in argv[1:]
    ]
    assert code == 0, "the helper did not commit"
    assert len(commits) == 1, calls
    argv, env = commits[0]
    assert not [arg for arg in argv if arg in FORBIDDEN_ARGS], argv
    assert "-F" in argv, argv
    assert env is not None, "the commit inherits the caller's git environment"
    leaked = sorted(
        key
        for key in env
        if key in POISON_KEYS
        or key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))
    )
    assert leaked == [], leaked
    assert lane.tip() != lane.base


# ---------------------------------------------------------------------------
# AC-785.8 — release of a landing card
# ---------------------------------------------------------------------------


def test_release_refuses_a_landing_card_until_the_lane_is_reset(lane: Lane) -> None:
    _put_card(lane, _card(lane, state="landing", op=OP_ID))
    before = _state(lane)
    proc = _release(lane)
    _refused(proc, "release_unreset")
    assert _state(lane) == before


def test_release_frees_a_landing_card_once_its_worktree_is_removed(lane: Lane) -> None:
    _put_card(lane, _card(lane, state="landing", op=OP_ID))
    _git(lane.main, "worktree", "remove", "--force", str(lane.wt))
    proc = _release(lane)
    _ok(proc)
    card = json.loads(lane.card_path.read_text(encoding="utf-8"))
    assert card["state"] == "released" and card["op"] is None, card


# ---------------------------------------------------------------------------
# AC-785.10 — a stage-1 card (branch null) keeps working
# ---------------------------------------------------------------------------


def test_a_stage_one_card_keeps_working_for_beat_list_and_release(lane: Lane) -> None:
    _put_card(lane, _card(lane, branch=None))
    _ok(_run(lane.wt, "beat", "--plan", f"{PLANS}/{SLUG}", "--session", SESSION))
    listing = json.loads(_ok(_run(lane.main, "list", "--json")))
    assert [(item["lane"], item["branch"]) for item in listing] == [(SLUG, None)]
    _git(lane.main, "worktree", "remove", "--force", str(lane.wt))
    _ok(_release(lane))
    card = json.loads(lane.card_path.read_text(encoding="utf-8"))
    assert card["state"] == "released" and card["branch"] is None, card
