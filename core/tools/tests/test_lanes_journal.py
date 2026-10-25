"""MEU-785 AC-785.11–.12: the land journal core and the per-op recovery lease — red first (G19).

FIC: ``docs/execution/plans/2026-10-22-lane-branches-governed-land/implementation-plan.md``
AC-785.11 (design D:240, D:427) and AC-785.12 (design D:166, §10b N-6).

- AC-785.11: land ops journal in the commit_batch op store through commit_batch's
  own journal writer (the land phases of the boundary inventory live there);
  ``tools/lanes.py`` never opens ``op.json`` for write. The census scans the
  source of ``tools/lanes.py`` and checks itself on synthetic sources first.
- AC-785.12: the per-op recovery lease ``<common>/lanes/ops/<op>.lease`` takes one
  attempt; a second process on the same op gets ``op_busy``, exit 3, no write.
  The lock-order test records every ``os_lease.acquire``/``release`` while the
  lane commit helper runs in process, and checks the design order (lane lease →
  main-tree lease → registry lock → ``store.lock``) with the registry lock never
  held while a lease is awaited; an injected out-of-order sequence must fail the
  same check.

Every repository is disposable, in ``tmp_path``, with system and global git config
cut off; the lock holder is a separate process with this file's own copy of the
lock protocol (from ``test_lanes.py``, copied, not imported). Tests reach new
symbols at run time. Do not skip, only, or early-return (G36).
"""

from __future__ import annotations

import ast
import importlib
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import pytest

from tools.tests import lane_worktree_config as lwc

ROOT = Path(__file__).resolve().parents[2]
LANES = ROOT / "tools" / "lanes.py"
COMMIT_BATCH = ROOT / "tools" / "commit_batch.py"
PLANS = "docs/execution/plans"
SLUG = "2026-10-20-lane-a"
OP_ID = "op-lane-a-1"
SESSION = "s-one"
WAIT_S = 0.2
POLL_S = 0.01
CLI_TIMEOUT_S = 120
GATE_LOCK = "{{PROJECT_NAME}}-gate.lock"
SESSION_ENV = "{{PROJECT_NAME_UPPER}}_SESSION"
# The land phases of the boundary inventory (IP "Land journal entries" row).
LAND_PHASES = (
    "land:freeze",
    "land:rebase",
    "land:conflict",
    "land:integrate",
    "land:kept",
    "land:ready",
    "land:authorized",
    "land:sync",
    "land:closed",
)
WRITE_CALLS = frozenset(
    {"write_text", "write_bytes", "_write_atomic", "_replace_atomically"}
)
OP_PATH_MARKS = ("op.json", ".file", "OP_FILE")

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
HOLDER_BODY = '{"pid": {pid}, "argv": ["holder.py", "land", "recover", "--op", "x"]}'


def _module(name: str) -> ModuleType:
    return importlib.import_module(name)


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert proc.returncode == 0, (args, proc.stdout, proc.stderr)
    return proc.stdout


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def _task_text(owns: list[str]) -> str:
    return (
        "---\nproject: fixture\n---\n\n# Task\n\n| # | Task |\n|---|---|\n| 1 | work |\n"
        "\n## Lane Ownership\n\n```yaml\nowns:\n"
        + "".join(f"  - {item}\n" for item in owns)
        + "must_not_touch: []\n```\n"
    )


@dataclass
class Lane:
    main: Path
    wt: Path
    common: Path
    base: str

    @property
    def lanes_dir(self) -> Path:
        return self.common / "lanes"

    @property
    def branch_ref(self) -> str:
        return f"refs/heads/lane/{SLUG}"


@pytest.fixture
def lane(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Lane:
    """One repository on ``main`` and one linked worktree on ``lane/<SLUG>``.

    The worktree folder, the plan folder and the branch suffix share one slug, so
    every reading of ``lane/<slug>`` names the same branch.
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
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    _git(main, "config", "core.hooksPath", hooks.as_posix())
    _write(main / "src" / "a.py", "A = 1\n")
    _write(main / lwc.WORKTREE_CONFIG, lwc.WORKTREE_CONFIG_TEXT)
    _write(main / PLANS / SLUG / "task.md", _task_text(["src/"]))
    _git(main, "add", "-A")
    _git(main, "commit", "-q", "-m", "fixture")
    base = _git(main, "rev-parse", "HEAD").strip()
    wt = tmp_path / SLUG
    _git(main, "worktree", "add", "-q", "-b", f"lane/{SLUG}", str(wt))
    common = Path(
        _git(main, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    ).resolve()
    return Lane(main=main.resolve(), wt=wt.resolve(), common=common, base=base)


def _run(
    cwd: Path, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    full_env = dict(os.environ)
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


def _tree_snapshot(root: Path, skip: Path) -> dict[str, bytes]:
    """Every file under ``root`` with its bytes, except ``skip`` (the held lease)."""
    out: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and path != skip:
            out[path.relative_to(root).as_posix()] = path.read_bytes()
    return out


# ---------------------------------------------------------------------------
# AC-785.11 census
# ---------------------------------------------------------------------------


def _mode_of(call: ast.Call, position: int) -> str | None:
    arg = call.args[position] if len(call.args) > position else None
    if isinstance(arg, ast.Constant):
        value = arg.value
        return value if isinstance(value, str) else None
    for keyword in call.keywords:
        if keyword.arg == "mode" and isinstance(keyword.value, ast.Constant):
            value = keyword.value.value
            return value if isinstance(value, str) else None
    return None


def _op_write_findings(source: str) -> list[str]:
    """Every call in ``source`` that opens or writes an op-file path for writing.

    A call counts when it writes (``open``/``.open`` with a ``w``/``a``/``x``/``+``
    mode, ``os.open``, ``write_text``, ``write_bytes``, ``_write_atomic``,
    ``_replace_atomically``) and its source text names an op file
    (``op.json``, an ``Op.file`` attribute, or an ``OP_FILE`` constant).
    """
    tree = ast.parse(source)
    findings: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        writes = False
        if name == "open":
            if (
                isinstance(func, ast.Attribute)
                and getattr(func.value, "id", "") == "os"
            ):
                writes = True
            else:
                mode = _mode_of(node, 0 if isinstance(func, ast.Attribute) else 1)
                writes = mode is not None and any(ch in mode for ch in "wax+")
        elif name in WRITE_CALLS:
            writes = True
        if not writes:
            continue
        text = ast.get_source_segment(source, node) or ""
        if any(mark in text for mark in OP_PATH_MARKS):
            findings.append(f"{node.lineno}:{text.splitlines()[0]}")
    return findings


def _imports_commit_batch(source: str) -> bool:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import) and any(
            alias.name.split(".")[-1] == "commit_batch" for alias in node.names
        ):
            return True
        if isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[-1] == "commit_batch":
                return True
            if any(alias.name == "commit_batch" for alias in node.names):
                return True
    return False


def test_lanes_never_write_opens_an_op_file_and_journals_through_commit_batch() -> None:
    # The census catches each write shape on a synthetic source, and passes a reader.
    bad = (
        "import os, json\n"
        "def f(folder, ctx, data):\n"
        "    open(folder / 'op.json', 'w').write(data)\n"
        "    (folder / 'op.json').write_text(data)\n"
        "    ctx.file.open('ab')\n"
        "    os.open(str(folder / 'op.json'), os.O_WRONLY)\n"
        "    _write_atomic(ctx.file, data)\n"
    )
    assert len(_op_write_findings(bad)) == 5, _op_write_findings(bad)
    good = "def g(folder):\n    return open(folder / 'op.json', 'rb').read()\n"
    assert _op_write_findings(good) == []
    assert _imports_commit_batch("from . import commit_batch\n")
    assert not _imports_commit_batch("import json\n")

    source = LANES.read_text(encoding="utf-8")
    assert _op_write_findings(source) == [], "tools/lanes.py writes an op file itself"
    assert _imports_commit_batch(source), (
        "tools/lanes.py must journal land ops through commit_batch's own journal writer"
    )
    writer = COMMIT_BATCH.read_text(encoding="utf-8")
    missing = [phase for phase in LAND_PHASES if f'"{phase}"' not in writer]
    assert missing == [], f"commit_batch.py journal writer lacks land phases {missing}"


# ---------------------------------------------------------------------------
# AC-785.12 per-op recovery lease
# ---------------------------------------------------------------------------


def test_a_second_recovery_of_the_same_op_is_op_busy_and_writes_nothing(
    lane: Lane,
) -> None:
    lease = lane.lanes_dir / "ops" / f"{OP_ID}.lease"
    holder = _Holder(lease)
    try:
        before = _tree_snapshot(lane.common, skip=lease)
        proc = _run(
            lane.wt, "land", "recover", "--op", OP_ID, env={SESSION_ENV: SESSION}
        )
        after = _tree_snapshot(lane.common, skip=lease)
    finally:
        holder.stop()
    assert proc.returncode == 3, (proc.returncode, proc.stdout, proc.stderr)
    assert "op_busy" in proc.stdout, (proc.stdout, proc.stderr)
    assert after == before, "a busy recovery wrote into the common dir"


# ---------------------------------------------------------------------------
# AC-785.12 lock order
# ---------------------------------------------------------------------------

RANK_NAMES = {
    1: "lane lease",
    2: "main-tree lease",
    3: "registry lock",
    4: "store.lock",
}


def _rank(path: Path, common: Path) -> int:
    """The design lock rank of a lease path (D:166); 0 for an unknown lock."""
    resolved = Path(path).resolve()
    if resolved.name == "registry.lock" and resolved.parent == common / "lanes":
        return 3
    if resolved.name == "store.lock":
        return 4
    if resolved.name == GATE_LOCK:
        if resolved.parent == common:
            return 2
        if resolved.parent.parent == common / "worktrees":
            return 1
    return 0


def _order_violations(events: list[tuple[str, int]]) -> list[str]:
    """Check ``(acquire|release, rank)`` events against the design order.

    Each acquire must outrank every lock already held, an unknown lock (rank 0)
    is a violation, and no lease (rank 1 or 2) may be awaited while the registry
    lock (rank 3) is held.
    """
    held: list[int] = []
    problems: list[str] = []
    for index, (kind, rank) in enumerate(events):
        if kind == "acquire":
            if rank == 0:
                problems.append(f"{index}: unknown lock")
            if rank in (1, 2) and 3 in held:
                problems.append(
                    f"{index}: {RANK_NAMES[rank]} awaited under the registry lock"
                )
            if held and rank <= max(held):
                problems.append(
                    f"{index}: {RANK_NAMES.get(rank, 'unknown')} after "
                    f"{RANK_NAMES.get(max(held), 'unknown')}"
                )
            held.append(rank)
        elif rank in held:
            held.remove(rank)
    return problems


def test_the_lane_commit_helper_takes_its_locks_in_the_design_order(
    lane: Lane, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The check itself: the design order passes, an injected out-of-order acquire fails.
    assert (
        _order_violations(
            [("acquire", 1), ("acquire", 3), ("release", 3), ("release", 1)]
        )
        == []
    )
    assert _order_violations([("acquire", 3), ("acquire", 1)]) != []
    assert _order_violations([("acquire", 2), ("acquire", 1)]) != []

    claim = _run(
        lane.wt,
        "claim",
        "--plan",
        f"{PLANS}/{SLUG}",
        "--worktree",
        str(lane.wt),
        "--session",
        SESSION,
    )
    assert claim.returncode == 0, (claim.stdout, claim.stderr)
    _write(lane.wt / "src" / "b.py", "B = 1\n")
    _git(lane.wt, "add", "src/b.py")
    message = lane.wt.parent / "message.txt"
    message.write_bytes(b"lane: add b\n")

    os_lease = _module("tools.os_lease")
    lanes = _module("tools.lanes")
    events: list[tuple[str, int]] = []
    real_acquire = os_lease.acquire
    real_release = os_lease.release

    def acquire(path: Path, **kwargs: object) -> object:
        events.append(("acquire", _rank(Path(path), lane.common)))
        return real_acquire(path, **kwargs)

    def release(lease: object) -> None:
        events.append(("release", _rank(Path(getattr(lease, "path")), lane.common)))
        real_release(lease)

    monkeypatch.setattr(os_lease, "acquire", acquire)
    monkeypatch.setattr(os_lease, "release", release)
    monkeypatch.setenv(SESSION_ENV, SESSION)
    monkeypatch.chdir(lane.wt)
    code = lanes.main(
        ["commit", "--worktree", str(lane.wt), "--message-file", str(message)],
        wait_s=WAIT_S,
        poll_s=POLL_S,
    )
    assert code == 0, "the lane commit helper did not commit"
    acquired = [rank for kind, rank in events if kind == "acquire"]
    assert 1 in acquired and 3 in acquired, (
        "the helper takes the lane lease and the registry lock",
        events,
    )
    assert _order_violations(events) == [], events
