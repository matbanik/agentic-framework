"""Tests of ``tools/session_wait.py`` and its skill page (MEU-963, AC-963.1 to AC-963.15).

The tests import the tool inside a helper, so an absent tool fails each test and
causes no collection error. ``ROOT`` is two levels above this folder, so one file
runs in both trees that carry the tool. A fake clock and a fake sleep drive the
wait loop. The fake runner gives canned output for the named tool readers and
sends every other command (git, and the readers with no canned output) to the
tool's own real runner.
"""

from __future__ import annotations

import importlib
import json
import re
import sqlite3
import subprocess
import sys
import textwrap
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
SKILL = ROOT / ".agent" / "skills" / "session-wait" / "SKILL.md"
COMMANDS = ROOT / ".agent" / "docs" / "commands.md"
SLUG = "2026-01-01-demo-plan"
TASK_REL = f"docs/execution/plans/{SLUG}/task.md"
DIRECTION = (
    "--direction-session",
    "sess-1",
    "--direction-message",
    "msg-1",
    "--direction-quote",
    "go ahead with the demo",
)
RECORD_KEYS = {
    "schema",
    "name",
    "plan",
    "conditions",
    "exemptions",
    "owner",
    "pid",
    "state",
    "direction",
    "poll_s",
    "stable_s",
    "cap_s",
    "armed_utc",
    "stable_since_utc",
    "last_check",
    "ended_utc",
    "timeout",
}
# A drive letter, a colon and a slash: the precedent of tests/tooling/test_agent_notify_docs.py.
DRIVE_PATH = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]")
# A child process that holds the lease of one wait until its standard input closes.
HOLDER = textwrap.dedent(
    """
    import sys
    from pathlib import Path
    sys.path.insert(0, sys.argv[1])
    import os_lease
    lease = os_lease.acquire(Path(sys.argv[2]), wait_s=5, body=sys.argv[3].encode("utf-8"))
    print("held", flush=True)
    sys.stdin.read()
    os_lease.release(lease)
    """
)

Reply = tuple[int, str, str] | BaseException


def _tool() -> ModuleType:
    """Import the tool under test; an absent tool fails the calling test."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    return importlib.import_module("tools.session_wait")


def _git(repo: Path, *args: str) -> str:
    """Run one git command in ``repo``; a failure fails the test."""
    done = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert done.returncode == 0, f"git {' '.join(args)}: {done.stderr}"
    return done.stdout


def _task_text(status: str, gate: str = "armed") -> str:
    """A task.md with a frontmatter that carries ``status`` and ``stop_gate``."""
    return f'---\nstatus: "{status}"\nstop_gate: "{gate}"\n---\n\n# Task\n'


def _write_task(repo: Path, status: str, gate: str = "armed", *, commit: bool) -> None:
    """Write the demo plan's task.md, and commit it on ``main`` when asked."""
    path = repo / TASK_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_task_text(status, gate), encoding="utf-8", newline="\n")
    if commit:
        _git(repo, "add", "--", TASK_REL)
        _git(repo, "commit", "-q", "-m", f"task {status}")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repository on ``main`` with one committed task.md in status ``approved``."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.name", "Fixture User")
    _git(root, "config", "user.email", "fixture@example.com")
    _git(root, "config", "core.autocrlf", "false")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "src").mkdir()
    (root / "src" / "kept.txt").write_text("kept\n", encoding="utf-8", newline="\n")
    _git(root, "add", "--", "src/kept.txt")
    _git(root, "commit", "-q", "-m", "base")
    _write_task(root, "approved", commit=True)
    return root


@dataclass
class World:
    """The fake clock, the fake sleep, the fake runner and the captured output."""

    mod: ModuleType
    t: float = 0.0
    sleeps: list[float] = field(default_factory=lambda: [])
    on_sleep: Callable[[int], None] | None = None
    canned: dict[str, list[Reply]] = field(default_factory=lambda: {})
    calls: list[tuple[str, Path, float]] = field(default_factory=lambda: [])
    lines: list[str] = field(default_factory=lambda: [])
    events: list[str] = field(default_factory=lambda: [])

    def clock(self) -> float:
        """The fake monotonic clock."""
        return self.t

    def sleep(self, seconds: float) -> None:
        """Advance the clock; then let the test change the world."""
        self.events.append("sleep")
        self.sleeps.append(seconds)
        self.t += seconds
        if self.on_sleep is not None:
            self.on_sleep(len(self.sleeps))

    def run(
        self, argv: Sequence[str], *, cwd: Path, timeout: float
    ) -> subprocess.CompletedProcess[str]:
        """Answer a canned reader, or pass the command to the tool's real runner."""
        name = Path(argv[1]).name if len(argv) > 1 else Path(argv[0]).name
        self.events.append(f"run:{name}")
        self.calls.append((name, Path(cwd), timeout))
        replies = self.canned.get(name)
        if replies:
            reply = replies.pop(0) if len(replies) > 1 else replies[0]
            if isinstance(reply, BaseException):
                raise reply
            code, out, err = reply
            return subprocess.CompletedProcess(list(argv), code, out, err)
        return self.mod.real_run(argv, cwd=cwd, timeout=timeout)

    def call(self, *args: str) -> int:
        """Run the tool's ``main`` with the fake seams."""
        env = self.mod.Env(
            run=self.run,
            clock=self.clock,
            sleep=self.sleep,
            out=self.lines.append,
            pid=4242,
        )
        return self.mod.main(list(args), env=env)


def _world() -> World:
    return World(mod=_tool())


def _rp(done: bool, reasons: Sequence[str]) -> Reply:
    """A canned ``run_parameters.py status --json`` answer after one other line."""
    body = {"done": done, "enabled": True, "reasons": list(reasons), "result": "status"}
    return (0, "note: a line before the object\n" + json.dumps(body) + "\n", "")


def _pf(missing: Sequence[str]) -> Reply:
    """A canned ``completion_preflight.py --json`` answer."""
    body = {"ok": not missing, "missing": list(missing), "details": {}}
    return (1 if missing else 0, json.dumps(body) + "\n", "")


def _lanes(entries: list[dict[str, object]], *, halt: bool = False) -> Reply:
    """A canned ``lanes.py list --json`` answer."""
    return (0, json.dumps(entries, indent=2) + "\n", "HALT\n" if halt else "")


def _files(root: Path) -> set[str]:
    """Every file and folder under ``root``, as relative paths."""
    return {p.relative_to(root).as_posix() for p in root.rglob("*")}


def _wait_dir(repo: Path) -> Path:
    return repo / ".git" / "session-wait"


def _record(name: str, state: str, **changes: object) -> dict[str, object]:
    """A valid wait record of schema ``session-wait/1``."""
    record: dict[str, object] = {
        "schema": "session-wait/1",
        "name": name,
        "plan": SLUG,
        "conditions": ["paths_clean:src"],
        "exemptions": [],
        "owner": "sess-0",
        "pid": 1,
        "state": state,
        "direction": {"session": "s0", "message": "m0", "quote": "q0"},
        "poll_s": 120,
        "stable_s": 300,
        "cap_s": 259200,
        "armed_utc": "2026-01-01T00:00:00Z",
        "stable_since_utc": None,
        "last_check": None,
        "ended_utc": None,
        "timeout": None,
    }
    record.update(changes)
    return record


def _put_record(repo: Path, record: dict[str, object] | str) -> Path:
    """Write a record (a dict, or raw text) into the wait folder."""
    folder = _wait_dir(repo)
    folder.mkdir(parents=True, exist_ok=True)
    if isinstance(record, str):
        name = "broken"
        text = record
    else:
        name = str(record["name"])
        text = json.dumps(record, indent=2) + "\n"
    path = folder / f"{name}.json"
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def _read_record(repo: Path, name: str) -> dict[str, object]:
    data = json.loads((_wait_dir(repo) / f"{name}.json").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data  # pyright: ignore[reportUnknownVariableType]


class Holder:
    """A child process that holds the lease of one wait name."""

    def __init__(self, repo: Path, name: str, body: str) -> None:
        folder = _wait_dir(repo)
        folder.mkdir(parents=True, exist_ok=True)
        self.proc = subprocess.Popen(
            [
                sys.executable,
                "-c",
                HOLDER,
                str(TOOLS),
                str(folder / f"{name}.lock"),
                body,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        assert self.proc.stdout is not None
        assert self.proc.stdout.readline().strip() == "held"

    def stop(self) -> None:
        """Close the child's standard input, so it releases the lease and ends."""
        assert self.proc.stdin is not None
        self.proc.stdin.close()
        self.proc.wait(timeout=20)


def _wait_args(
    repo: Path, name: str, *conds: str, extra: Sequence[str] = ()
) -> list[str]:
    args = [
        "--repo",
        str(repo),
        "wait",
        "--name",
        name,
        "--plan",
        SLUG,
        "--owner",
        "sess-1",
    ]
    for cond in conds:
        args += ["--cond", cond]
    return args + list(DIRECTION) + list(extra)


def _dirty(repo: Path) -> Path:
    path = repo / "src" / "new.txt"
    path.write_text("new\n", encoding="utf-8", newline="\n")
    return path


# --- AC-963.1: check --------------------------------------------------------------


def test_ag8_ac_963_1_check_not_holding_prints_reasons_and_exits_1(repo: Path) -> None:
    world = _world()
    _write_task(repo, "in_progress", commit=False)
    before = _files(repo)
    code = world.call(
        "--repo",
        str(repo),
        "check",
        "--cond",
        f"plan_idle:{SLUG}",
        "--cond",
        "paths_clean:docs",
    )
    assert code == 1
    assert world.lines == [
        f"wait plan_idle:{SLUG}:in_progress paths_clean:docs:dirty:1"
    ]
    assert world.sleeps == []
    assert _files(repo) == before


def test_ag8_ac_963_1_check_holding_prints_hold_and_exits_0(repo: Path) -> None:
    world = _world()
    before = _files(repo)
    code = world.call(
        "--repo",
        str(repo),
        "check",
        "--cond",
        f"plan_idle:{SLUG}",
        "--cond",
        "paths_clean:src",
    )
    assert code == 0
    assert world.lines == ["hold"]
    assert world.sleeps == []
    assert _files(repo) == before
    assert not _wait_dir(repo).exists()


# --- AC-963.2: wait loop ----------------------------------------------------------


def test_ag8_ac_963_2_defaults_poll_120_stable_300_cap_72_hours(repo: Path) -> None:
    world = _world()
    assert (world.mod.POLL_S, world.mod.STABLE_S, world.mod.CAP_S) == (120, 300, 259200)
    code = world.call(*_wait_args(repo, "defaults", "paths_clean:src"))
    assert code == 0
    assert world.sleeps == [120, 120, 120]
    assert world.lines[-1] == "wait_ok hold"
    record = _read_record(repo, "defaults")
    assert (record["poll_s"], record["stable_s"], record["cap_s"]) == (120, 300, 259200)


def test_ag8_ac_963_2_first_check_comes_before_the_first_sleep(repo: Path) -> None:
    world = _world()
    code = world.call(
        *_wait_args(repo, "first", "paths_clean:src", extra=["--stable-s", "0"])
    )
    assert code == 0
    assert world.sleeps == []
    assert "sleep" not in world.events
    assert world.lines[-1] == "wait_ok hold"


def test_ag8_ac_963_2_a_break_in_the_hold_resets_the_stable_time(repo: Path) -> None:
    world = _world()
    made: list[Path] = []

    def change(n: int) -> None:
        if n == 1:
            made.append(_dirty(repo))
        if n == 2:
            made[0].unlink()

    world.on_sleep = change
    code = world.call(*_wait_args(repo, "reset", "paths_clean:src"))
    assert code == 0
    # Hold at 0, break at 120, hold again from 240: it fires at 600, not at 360.
    assert world.sleeps == [120, 120, 120, 120, 120]
    assert world.t == 600


def test_ag8_ac_963_2_cap_with_no_stable_hold_gives_wait_timeout_exit_5(
    repo: Path,
) -> None:
    world = _world()
    _dirty(repo)
    code = world.call(
        *_wait_args(repo, "capped", "paths_clean:src", extra=["--cap-s", "600"])
    )
    assert code == 5
    assert world.lines[-1] == "wait_timeout last: wait paths_clean:src:dirty:1"
    assert world.t == 600
    record = _read_record(repo, "capped")
    assert record["state"] == "timeout"
    timeout = record["timeout"]
    assert isinstance(timeout, dict)
    assert timeout["limit_name"] == "cap_s"  # pyright: ignore[reportUnknownMemberType]
    assert timeout["configured_value"] == 600  # pyright: ignore[reportUnknownMemberType]
    assert timeout["observed_value"] == 600  # pyright: ignore[reportUnknownMemberType]
    assert "window" in timeout


def test_ag8_ac_963_2_options_change_the_three_values(repo: Path) -> None:
    world = _world()
    code = world.call(
        *_wait_args(
            repo,
            "options",
            "paths_clean:src",
            extra=["--poll-s", "10", "--stable-s", "25", "--cap-s", "1000"],
        )
    )
    assert code == 0
    assert world.sleeps == [10, 10, 10]
    record = _read_record(repo, "options")
    assert (record["poll_s"], record["stable_s"], record["cap_s"]) == (10, 25, 1000)


# --- AC-963.3: receipt ------------------------------------------------------------


def test_ag8_ac_963_3_receipt_has_one_line_per_change_and_ends_with_the_token(
    repo: Path,
) -> None:
    world = _world()
    made = _dirty(repo)

    def change(n: int) -> None:
        if n == 2:
            made.unlink()

    world.on_sleep = change
    code = world.call(
        *_wait_args(repo, "receipt", "paths_clean:src", extra=["--stable-s", "0"])
    )
    assert code == 0
    receipt = (_wait_dir(repo) / "receipt.log").read_text(encoding="utf-8").splitlines()
    # Two equal checks (passes 1 and 2) write one line, not two.
    assert len(receipt) == 3
    assert receipt[0].endswith("wait paths_clean:src:dirty:1")
    assert receipt[1].endswith("hold")
    assert receipt[-1] == "wait_ok hold"
    assert world.lines == receipt


def test_ag8_ac_963_3_receipt_is_fresh_at_each_arm_and_option_moves_it(
    repo: Path, tmp_path: Path
) -> None:
    world = _world()
    made = _dirty(repo)
    assert (
        world.call(
            *_wait_args(repo, "again", "paths_clean:src", extra=["--cap-s", "120"])
        )
        == 5
    )
    made.unlink()
    world2 = _world()
    assert (
        world2.call(
            *_wait_args(repo, "again", "paths_clean:src", extra=["--stable-s", "0"])
        )
        == 0
    )
    receipt = (_wait_dir(repo) / "again.log").read_text(encoding="utf-8")
    assert "wait_timeout" not in receipt
    assert receipt.splitlines()[-1] == "wait_ok hold"
    own = tmp_path / "own-receipt.txt"
    world3 = _world()
    code = world3.call(
        *_wait_args(
            repo,
            "moved",
            "paths_clean:src",
            extra=["--stable-s", "0", "--receipt", str(own)],
        )
    )
    assert code == 0
    assert own.read_text(encoding="utf-8").splitlines()[-1] == "wait_ok hold"
    assert not (_wait_dir(repo) / "moved.log").exists()


# --- AC-963.4: plan_done ----------------------------------------------------------


def _done_world(rp: Reply, pf: Reply) -> World:
    world = _world()
    world.canned = {"run_parameters.py": [rp], "completion_preflight.py": [pf]}
    return world


def _land(repo: Path) -> None:
    _write_task(repo, "complete", "released:done", commit=True)


def test_ag8_ac_963_4_plan_done_holds_with_the_four_facts(repo: Path) -> None:
    _land(repo)
    world = _done_world(_rp(True, []), _pf([]))
    code = world.call("--repo", str(repo), "check", "--cond", f"plan_done:{SLUG}")
    assert code == 0
    assert world.lines == ["hold"]
    names = [name for name, _, _ in world.calls]
    assert "run_parameters.py" in names
    assert "completion_preflight.py" in names


@pytest.mark.parametrize(
    ("removed", "rp", "pf", "landed", "reason"),
    [
        ("released_done", _rp(False, ["not_done"]), _pf([]), True, "not_done"),
        ("verdict", _rp(True, []), _pf(["approved_verdict"]), True, "no_verdict"),
        (
            "preflight",
            _rp(True, []),
            _pf(["handoff", "metrics"]),
            True,
            "preflight:handoff+metrics",
        ),
        ("land_commit", _rp(True, []), _pf([]), False, "not_landed"),
    ],
)
def test_ag8_ac_963_4_plan_done_each_removed_fact_gives_its_reason(
    repo: Path, removed: str, rp: Reply, pf: Reply, landed: bool, reason: str
) -> None:
    if landed:
        _land(repo)
    world = _done_world(rp, pf)
    code = world.call("--repo", str(repo), "check", "--cond", f"plan_done:{SLUG}")
    assert code == 1, removed
    assert world.lines == [f"wait plan_done:{SLUG}:{reason}"], removed


def test_ag8_ac_963_4_plan_done_has_no_short_circuit_and_a_fixed_order(
    repo: Path,
) -> None:
    world = _done_world(_rp(False, ["not_done"]), _pf(["approved_verdict", "handoff"]))
    code = world.call("--repo", str(repo), "check", "--cond", f"plan_done:{SLUG}")
    assert code == 1
    assert world.lines == [
        f"wait plan_done:{SLUG}:not_done,no_verdict,preflight:handoff,not_landed"
    ]


@pytest.mark.parametrize(
    ("rp", "pf", "reason"),
    [
        (_rp(False, ["disabled"]), _pf([]), "disabled"),
        ((0, "no object here\n", ""), _pf([]), "reader_failed:status"),
        ((0, '{"done": "yes"}\n', ""), _pf([]), "reader_failed:status"),
        (
            _rp(True, []),
            (2, "usage: completion_preflight.py\n", ""),
            "reader_failed:preflight",
        ),
        (_rp(True, []), (1, "not json\n", ""), "reader_failed:preflight"),
    ],
)
def test_ag8_ac_963_4_plan_done_reader_failure_and_disabled_do_not_hold(
    repo: Path, rp: Reply, pf: Reply, reason: str
) -> None:
    _land(repo)
    world = _done_world(rp, pf)
    code = world.call("--repo", str(repo), "check", "--cond", f"plan_done:{SLUG}")
    assert code == 1
    assert world.lines == [f"wait plan_done:{SLUG}:{reason}"]


def test_ag8_ac_963_4_plan_done_reader_timeout_does_not_hold(repo: Path) -> None:
    _land(repo)
    world = _done_world(
        subprocess.TimeoutExpired(cmd="run_parameters.py", timeout=120), _pf([])
    )
    code = world.call("--repo", str(repo), "check", "--cond", f"plan_done:{SLUG}")
    assert code == 1
    assert world.lines == [f"wait plan_done:{SLUG}:reader_timeout:status"]
    assert world.mod.READER_TIMEOUT_S == 120
    timeouts = {name: timeout for name, _, timeout in world.calls}
    assert timeouts["run_parameters.py"] == 120


# --- AC-963.5: plan_idle ----------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "code", "line"),
    [
        ("approved", 0, "hold"),
        ("complete", 0, "hold"),
        ("in_progress", 1, f"wait plan_idle:{SLUG}:in_progress"),
    ],
)
def test_ag8_ac_963_5_plan_idle_holds_when_not_in_progress(
    repo: Path, status: str, code: int, line: str
) -> None:
    _write_task(repo, status, commit=False)
    world = _world()
    assert (
        world.call("--repo", str(repo), "check", "--cond", f"plan_idle:{SLUG}") == code
    )
    assert world.lines == [line]


def test_ag8_ac_963_5_plan_idle_with_no_task_does_not_hold(repo: Path) -> None:
    world = _world()
    code = world.call(
        "--repo", str(repo), "check", "--cond", "plan_idle:2026-01-02-absent"
    )
    assert code == 1
    assert world.lines == ["wait plan_idle:2026-01-02-absent:no_task"]


# --- AC-963.6: lanes_free ---------------------------------------------------------


def test_ag8_ac_963_6_lanes_free_real_reader_in_an_empty_repo_holds(repo: Path) -> None:
    world = _world()
    code = world.call("--repo", str(repo), "check", "--cond", "lanes_free")
    assert code == 0
    assert world.lines == ["hold"]
    lanes_calls = [cwd for name, cwd, _ in world.calls if name == "lanes.py"]
    assert lanes_calls == [repo]


@pytest.mark.parametrize(
    ("entries", "halt", "line"),
    [
        (
            [{"lane": "lane-a", "state": "active", "stale": False}],
            False,
            "wait lanes_free:active:lane-a",
        ),
        (
            [{"lane": "lane-a", "state": "active", "stale": True}],
            False,
            "wait lanes_free:active:lane-a",
        ),
        (
            [{"lane": "lane-b", "state": "landing", "stale": False}],
            False,
            "wait lanes_free:landing:lane-b",
        ),
        (
            [{"lane": "lane-c", "state": "bad", "stale": None, "error": "x"}],
            False,
            "wait lanes_free:bad:lane-c",
        ),
        ([], True, "wait lanes_free:halt"),
    ],
)
def test_ag8_ac_963_6_lanes_free_busy_cards_and_halt_do_not_hold(
    repo: Path, entries: list[dict[str, object]], halt: bool, line: str
) -> None:
    world = _world()
    world.canned = {"lanes.py": [_lanes(entries, halt=halt)]}
    assert world.call("--repo", str(repo), "check", "--cond", "lanes_free") == 1
    assert world.lines == [line]


def test_ag8_ac_963_6_lanes_free_exemption_is_named_and_printed(repo: Path) -> None:
    world = _world()
    world.canned = {
        "lanes.py": [_lanes([{"lane": "lane-a", "state": "active", "stale": False}])]
    }
    code = world.call(
        "--repo", str(repo), "check", "--cond", "lanes_free", "--exempt", "lane-a:D-7"
    )
    assert code == 0
    assert world.lines == ["hold exempt=lane-a:D-7"]


def test_ag8_ac_963_6_lanes_free_halt_is_never_exempt(repo: Path) -> None:
    world = _world()
    entries: list[dict[str, object]] = [
        {"lane": "lane-a", "state": "active", "stale": False}
    ]
    world.canned = {"lanes.py": [_lanes(entries, halt=True)]}
    code = world.call(
        "--repo", str(repo), "check", "--cond", "lanes_free", "--exempt", "lane-a:D-7"
    )
    assert code == 1
    assert world.lines == ["wait lanes_free:halt exempt=lane-a:D-7"]


@pytest.mark.parametrize(
    ("reply", "line"),
    [
        ((0, "not json\n", ""), "wait lanes_free:reader_failed:shape"),
        ((0, '{"lane": "x"}\n', ""), "wait lanes_free:reader_failed:shape"),
        ((1, "", "refused\n"), "wait lanes_free:reader_failed"),
    ],
)
def test_ag8_ac_963_6_lanes_free_reader_failure_does_not_hold(
    repo: Path, reply: Reply, line: str
) -> None:
    world = _world()
    world.canned = {"lanes.py": [reply]}
    assert world.call("--repo", str(repo), "check", "--cond", "lanes_free") == 1
    assert world.lines == [line]


# --- AC-963.7: paths_clean --------------------------------------------------------


def test_ag8_ac_963_7_paths_clean_holds_on_clean_paths(repo: Path) -> None:
    world = _world()
    assert (
        world.call("--repo", str(repo), "check", "--cond", "paths_clean:src,docs") == 0
    )
    assert world.lines == ["hold"]


def test_ag8_ac_963_7_modified_or_untracked_file_does_not_hold(repo: Path) -> None:
    (repo / "src" / "kept.txt").write_text("changed\n", encoding="utf-8", newline="\n")
    world = _world()
    assert world.call("--repo", str(repo), "check", "--cond", "paths_clean:src") == 1
    assert world.lines == ["wait paths_clean:src:dirty:1"]
    _dirty(repo)
    world2 = _world()
    assert world2.call("--repo", str(repo), "check", "--cond", "paths_clean:src") == 1
    assert world2.lines == ["wait paths_clean:src:dirty:2"]


# --- AC-963.8: no_busy_run --------------------------------------------------------


def _store(
    path: Path,
    runs: Sequence[tuple[str, str, str]] = (),
    segments: Sequence[tuple[str, str, str, str | None]] = (),
    lanes: Sequence[tuple[str, str | None]] = (),
    *,
    finalized_column: bool = True,
) -> Path:
    """A fixture store with the columns that the ``no_busy_run`` reader reads."""
    con = sqlite3.connect(path)
    try:
        con.execute(
            "CREATE TABLE runs (run_id TEXT PRIMARY KEY, lane TEXT, state TEXT NOT NULL)"
        )
        if finalized_column:
            con.execute(
                "CREATE TABLE segments (segment_id TEXT PRIMARY KEY, lane TEXT, "
                "state TEXT NOT NULL, finalized_utc TEXT)"
            )
            con.executemany("INSERT INTO segments VALUES (?, ?, ?, ?)", segments)
        else:
            con.execute(
                "CREATE TABLE segments (segment_id TEXT PRIMARY KEY, lane TEXT, state TEXT NOT NULL)"
            )
        con.execute("CREATE TABLE lanes (lane TEXT PRIMARY KEY, segment_id TEXT)")
        con.executemany("INSERT INTO runs VALUES (?, ?, ?)", runs)
        con.executemany("INSERT INTO lanes VALUES (?, ?)", lanes)
        con.commit()
    finally:
        con.close()
    return path


LANE = "tree:fixture/main"


def _busy_check(repo: Path, db: Path, lane: str = LANE) -> tuple[int, list[str]]:
    world = _world()
    code = world.call(
        "--repo", str(repo), "check", "--cond", "no_busy_run",
        "--credits-db", str(db), "--credits-lane", lane,
    )  # fmt: skip
    return code, world.lines


def test_ag8_ac_963_8_real_store_from_credits_state_init_holds(
    repo: Path, tmp_path: Path
) -> None:
    db = tmp_path / "state.db"
    done = subprocess.run(
        [sys.executable, str(TOOLS / "credits_state.py"), "--db", str(db), "init"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    world = _world()
    code = world.call(
        "--repo", str(repo), "check", "--cond", "no_busy_run", "--credits-db", str(db)
    )
    assert code == 0
    assert world.lines == ["hold"]


@pytest.mark.parametrize(
    "state",
    [
        "registered",
        "stopped",
        "done",
        "done_unverified",
        "failed",
        "cancelled",
        "parked",
        "parked_x",
    ],
)
def test_ag8_ac_963_8_idle_runs_and_finalized_segments_hold(
    repo: Path, tmp_path: Path, state: str
) -> None:
    db = _store(
        tmp_path / "idle.db",
        runs=[("r1", LANE, state)],
        segments=[("s1", LANE, "finalized", "2026-01-01T00:00:00Z")],
        lanes=[(LANE, None)],
    )
    assert _busy_check(repo, db) == (0, ["hold"])


@pytest.mark.parametrize(
    ("runs", "segments", "lanes", "reason"),
    [
        ([("r1", LANE, "launching")], [], [], "run:r1=launching"),
        ([("r1", LANE, "waiting")], [], [], "run:r1=waiting"),
        ([("r1", LANE + "/lane-x", "running")], [], [], "run:r1=running"),
        ([], [("s1", LANE, "running", None)], [], "segment:s1=running"),
        ([], [("s1", LANE, "finalized", None)], [], "segment:s1=finalized"),
        ([], [], [(LANE, "s9")], f"lane:{LANE}=s9"),
    ],
)
def test_ag8_ac_963_8_busy_run_open_segment_and_claimed_lane_do_not_hold(
    repo: Path,
    tmp_path: Path,
    runs: list[tuple[str, str, str]],
    segments: list[tuple[str, str, str, str | None]],
    lanes: list[tuple[str, str | None]],
    reason: str,
) -> None:
    db = _store(tmp_path / "busy.db", runs=runs, segments=segments, lanes=lanes)
    assert _busy_check(repo, db) == (1, [f"wait no_busy_run:{reason}"])


def test_ag8_ac_963_8_other_lanes_do_not_count(repo: Path, tmp_path: Path) -> None:
    db = _store(tmp_path / "other.db", runs=[("r1", "tree:fixture/other", "launching")])
    assert _busy_check(repo, db) == (0, ["hold"])


def test_ag8_ac_963_8_missing_store_and_missing_column_do_not_hold(
    repo: Path, tmp_path: Path
) -> None:
    assert _busy_check(repo, tmp_path / "absent.db") == (
        1,
        ["wait no_busy_run:store_missing"],
    )
    db = _store(tmp_path / "old.db", finalized_column=False)
    assert _busy_check(repo, db) == (1, ["wait no_busy_run:store_unreadable"])


def test_ag8_ac_963_8_default_lane_is_the_main_tree(repo: Path, tmp_path: Path) -> None:
    lane = "tree:" + repo.resolve().as_posix()
    db = _store(tmp_path / "tree.db", runs=[("r1", lane, "launching")])
    world = _world()
    code = world.call(
        "--repo", str(repo), "check", "--cond", "no_busy_run", "--credits-db", str(db)
    )
    assert code == 1
    assert world.lines == ["wait no_busy_run:run:r1=launching"]


def test_ag8_ac_963_8_idle_states_agree_with_credits_state() -> None:
    mod = _tool()
    credits = importlib.import_module("tools.credits_state")
    expected = (
        set(credits.TERMINAL_RUN_STATES)
        | set(credits.HALTED_RUN_STATES)
        | {"registered"}
    )
    assert set(mod.IDLE_RUN_STATES) == expected
    assert "waiting" in credits.FIRST_START_FROM
    assert "waiting" not in mod.IDLE_RUN_STATES


# --- AC-963.9: record and direction -----------------------------------------------


def test_ag8_ac_963_9_wait_writes_one_record_with_the_direction(repo: Path) -> None:
    world = _world()
    code = world.call(
        *_wait_args(repo, "rec", "paths_clean:src", extra=["--stable-s", "0"])
    )
    assert code == 0
    assert sorted(p.name for p in _wait_dir(repo).glob("*.json")) == ["rec.json"]
    record = _read_record(repo, "rec")
    assert set(record) == RECORD_KEYS
    assert record["schema"] == "session-wait/1"
    assert record["plan"] == SLUG
    assert record["conditions"] == ["paths_clean:src"]
    assert record["owner"] == "sess-1"
    assert record["pid"] == 4242
    assert record["state"] == "fired"
    assert record["direction"] == {
        "session": "sess-1",
        "message": "msg-1",
        "quote": "go ahead with the demo",
    }
    last = record["last_check"]
    assert isinstance(last, dict)
    assert last["line"] == "hold"  # pyright: ignore[reportUnknownMemberType]
    assert isinstance(record["ended_utc"], str)


@pytest.mark.parametrize(
    "missing", ["--direction-session", "--direction-message", "--direction-quote"]
)
def test_ag8_ac_963_9_wait_with_no_direction_is_a_usage_error(
    repo: Path, missing: str
) -> None:
    args = _wait_args(repo, "nodir", "paths_clean:src")
    at = args.index(missing)
    del args[at : at + 2]
    world = _world()
    assert world.call(*args) == 2
    assert world.lines == [f"usage_error:missing:{missing}"]
    assert not _wait_dir(repo).exists()


# --- AC-963.10: list --------------------------------------------------------------


def test_ag8_ac_963_10_list_shows_who_waits_for_what(repo: Path) -> None:
    _put_record(
        repo,
        _record(
            "alpha", "armed", last_check={"utc": "x", "line": "wait a", "hold": False}
        ),
    )
    _put_record(repo, "{not json")
    _put_record(repo, _record("gamma", "fired"))
    holder = Holder(repo, "gamma", "sess-9:77")
    try:
        world = _world()
        assert world.call("--repo", str(repo), "list") == 0
        alpha = [line for line in world.lines if line.startswith("alpha ")]
        assert len(alpha) == 1
        for part in (
            "plan=" + SLUG,
            "state=armed",
            "owner=sess-0",
            "runner=dead",
            "conds=paths_clean:src",
        ):
            assert part in alpha[0], part
        assert "broken unreadable" in world.lines
        gamma = [line for line in world.lines if line.startswith("gamma ")]
        assert len(gamma) == 1
        assert "runner=alive" in gamma[0]
        world2 = _world()
        assert world2.call("--repo", str(repo), "list", "--json") == 0
        data = json.loads("\n".join(world2.lines))
        by_name = {item["name"]: item for item in data}
        assert by_name["alpha"]["runner"] == "dead"
        assert by_name["gamma"]["runner"] == "alive"
        assert by_name["broken"]["state"] == "unreadable"
    finally:
        holder.stop()
    assert not (_wait_dir(repo) / "alpha.lock").exists()


# --- AC-963.11: one runner --------------------------------------------------------


def test_ag8_ac_963_11_live_runner_is_refused_busy(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mod = _tool()
    assert mod.LEASE_WAIT_S == 5
    monkeypatch.setattr(mod, "LEASE_WAIT_S", 0.05)
    _put_record(repo, _record("live", "armed"))
    holder = Holder(repo, "live", "other-session:999")
    try:
        world = World(mod=mod)
        start = time.monotonic()
        code = world.call(
            *_wait_args(repo, "live", "paths_clean:src", extra=["--stable-s", "0"])
        )
        elapsed = time.monotonic() - start
    finally:
        holder.stop()
    assert code == 1
    assert world.lines[-1] == "wait_refused:busy:other-session:999"
    assert elapsed < 1.0
    assert _read_record(repo, "live")["owner"] == "sess-0"


@pytest.mark.parametrize("state", ["armed", "timeout"])
def test_ag8_ac_963_11_dead_runner_or_timeout_arms_again(
    repo: Path, state: str
) -> None:
    _put_record(repo, _record("again", state))
    world = _world()
    code = world.call(
        *_wait_args(repo, "again", "paths_clean:src", extra=["--stable-s", "0"])
    )
    assert code == 0
    record = _read_record(repo, "again")
    assert record["state"] == "fired"
    assert record["owner"] == "sess-1"
    assert record["pid"] == 4242


@pytest.mark.parametrize("state", ["fired", "used"])
def test_ag8_ac_963_11_fired_and_used_are_refused(repo: Path, state: str) -> None:
    _put_record(repo, _record("ended", state))
    world = _world()
    code = world.call(
        *_wait_args(repo, "ended", "paths_clean:src", extra=["--stable-s", "0"])
    )
    assert code == 1
    assert world.lines == [f"wait_refused:{state}"]
    assert _read_record(repo, "ended")["state"] == state


# --- AC-963.12: use ---------------------------------------------------------------


def test_ag8_ac_963_12_use_changes_fired_to_used_one_time(repo: Path) -> None:
    _put_record(repo, _record("once", "fired"))
    world = _world()
    assert world.call("--repo", str(repo), "use", "--name", "once") == 0
    assert world.lines == ["used once"]
    assert _read_record(repo, "once")["state"] == "used"
    world2 = _world()
    assert world2.call("--repo", str(repo), "use", "--name", "once") == 1
    assert world2.lines == ["use_refused:used"]


def test_ag8_ac_963_12_use_on_armed_or_busy_is_refused(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _put_record(repo, _record("early", "armed"))
    world = _world()
    assert world.call("--repo", str(repo), "use", "--name", "early") == 1
    assert world.lines == ["use_refused:armed"]
    mod = _tool()
    monkeypatch.setattr(mod, "LEASE_WAIT_S", 0.05)
    _put_record(repo, _record("held", "fired"))
    holder = Holder(repo, "held", "sess-5:55")
    try:
        world2 = World(mod=mod)
        code = world2.call("--repo", str(repo), "use", "--name", "held")
    finally:
        holder.stop()
    assert code == 1
    assert world2.lines == ["use_refused:busy:sess-5:55"]
    assert _read_record(repo, "held")["state"] == "fired"


# --- AC-963.13: closed set and usage ----------------------------------------------


@pytest.mark.parametrize(
    ("args", "reason"),
    [
        (["check", "--cond", "bogus"], "unknown_condition:bogus"),
        (["check", "--cond", "bogus:x"], "unknown_condition:bogus"),
        (
            ["check", "--cond", "lanes_free", "--cond", "lanes_free"],
            "duplicate_condition:lanes_free",
        ),
        (["check", "--cond", "plan_idle:../x"], "bad_slug:../x"),
        (["check", "--cond", "plan_done:"], "bad_slug:"),
        (["check", "--cond", "paths_clean:../x"], "bad_path:../x"),
        (["check", "--cond", "paths_clean:a\\b"], "bad_path:a\\b"),
        (["check", "--cond", "paths_clean:a,,b"], "bad_path:"),
        (["check", "--cond", "paths_clean:/abs"], "bad_path:/abs"),
        (["check", "--cond", "lanes_free:x"], "bad_argument:lanes_free"),
        (["check", "--cond", "no_busy_run:x"], "bad_argument:no_busy_run"),
        (["check", "--cond", "no_busy_run"], "no_busy_run_needs_credits_db"),
        (
            ["check", "--cond", "paths_clean:src", "--exempt", "a:D-1"],
            "exempt_needs_lanes_free",
        ),
        (
            ["check", "--cond", "lanes_free", "--exempt", "nocolon"],
            "bad_exempt:nocolon",
        ),
        (["check"], "missing:--cond"),
        (["bogus-verb"], "unknown_verb:bogus-verb"),
    ],
)
def test_ag8_ac_963_13_bad_arguments_are_usage_errors(
    repo: Path, args: list[str], reason: str
) -> None:
    world = _world()
    assert world.call("--repo", str(repo), *args) == 2
    assert world.lines == [f"usage_error:{reason}"]
    assert not _wait_dir(repo).exists()


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("Bad_Name", "bad_name:Bad_Name"),
        ("a/b", "bad_name:a/b"),
        ("a" * 65, "bad_name:" + "a" * 65),
    ],
)
def test_ag8_ac_963_13_bad_wait_name_is_a_usage_error(
    repo: Path, name: str, reason: str
) -> None:
    world = _world()
    args = _wait_args(repo, "placeholder", "paths_clean:src")
    args[args.index("placeholder")] = name
    assert world.call(*args) == 2
    assert world.lines == [f"usage_error:{reason}"]
    assert not _wait_dir(repo).exists()


def test_ag8_ac_963_13_record_with_unknown_key_is_refused_by_name(repo: Path) -> None:
    _put_record(repo, _record("odd", "timeout", extra_key=1))
    world = _world()
    code = world.call(
        *_wait_args(repo, "odd", "paths_clean:src", extra=["--stable-s", "0"])
    )
    assert code == 1
    assert world.lines == ["wait_refused:record_unreadable:odd"]
    world2 = _world()
    assert world2.call("--repo", str(repo), "use", "--name", "odd") == 1
    assert world2.lines == ["use_refused:record_unreadable:odd"]
    world3 = _world()
    assert world3.call("--repo", str(repo), "list") == 0
    assert "odd unreadable" in world3.lines


def test_ag8_ac_963_13_record_with_a_wrong_type_is_refused(repo: Path) -> None:
    _put_record(repo, _record("typed", "timeout", pid="seven"))
    world = _world()
    code = world.call(
        *_wait_args(repo, "typed", "paths_clean:src", extra=["--stable-s", "0"])
    )
    assert code == 1
    assert world.lines == ["wait_refused:record_unreadable:typed"]


# --- AC-963.14: skill page and commands.md ----------------------------------------


def _skill_text() -> str:
    assert SKILL.is_file(), "AC-963.14: the skill page is missing"
    return SKILL.read_text(encoding="utf-8")


def test_ag8_ac_963_14_skill_page_gives_forms_wake_path_and_rules() -> None:
    text = _skill_text()
    assert re.search(r"^name:\s*session-wait\s*$", text, re.MULTILINE)
    for verb in ("check", "wait", "list", "use"):
        assert re.search(rf"session_wait\.py {verb}\b", text), verb
    assert re.search(r"background command", text), "no wake path"
    assert re.search(r"exit wakes", text), "no wake path"
    assert re.search(r"named conditions", text), "no named conditions"
    assert re.search(r"carries no authority", text), "no authority rule"
    assert "tools/run_parameters.py verify" in text
    assert re.search(r"\bR0\b", text)
    assert re.search(r"context small", text), "no context rule"


def test_ag8_ac_963_14_commands_md_has_the_group_and_the_skills_row() -> None:
    assert COMMANDS.is_file()
    lines = COMMANDS.read_text(encoding="utf-8").splitlines()
    patterns = [
        r"^uv run python tools/session_wait\.py check --cond ",
        r"^uv run python tools/session_wait\.py wait --name ",
        r"^uv run python tools/session_wait\.py list\b",
        r"^uv run python tools/session_wait\.py use --name ",
        r"^\| Session Wait \| `\.agent/skills/session-wait/SKILL\.md` \|",
    ]
    for pattern in patterns:
        found = [line for line in lines if re.search(pattern, line)]
        assert len(found) == 1, pattern


# --- AC-963.15: no names ----------------------------------------------------------


def _project_names() -> set[str]:
    """Names of this project, read at run time; names under four characters are ignored."""
    names: set[str] = set()
    for folder in (ROOT, *ROOT.parents):
        if (folder / ".git").exists():
            names.add(folder.name)
            break
    pyproject = ROOT / "pyproject.toml"
    if pyproject.is_file():
        match = re.search(
            r'^name\s*=\s*"([^"]+)"',
            pyproject.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
        if match:
            names.add(match.group(1))
    return {name.lower() for name in names if len(name) >= 4}


def _leaks(text: str, names: set[str]) -> list[str]:
    """Drive paths and project names in ``text``."""
    found = [m.group(0) for m in DRIVE_PATH.finditer(text)]
    lowered = text.lower()
    found += [name for name in sorted(names) if name in lowered]
    return found


def test_ag8_ac_963_15_tool_and_skill_hold_no_drive_path_and_no_project_name() -> None:
    tool = TOOLS / "session_wait.py"
    assert tool.is_file(), "AC-963.15: the tool is missing"
    names = _project_names()
    assert _leaks(tool.read_text(encoding="utf-8"), names) == []
    assert _leaks(_skill_text(), names) == []
    # The blind arm: a planted drive path and a planted name are found.
    drive = "Q" + ":/"
    planted = f"see {drive}work/thing and the Projectx tree"
    assert _leaks(planted, {"projectx"}) == [drive, "projectx"]
