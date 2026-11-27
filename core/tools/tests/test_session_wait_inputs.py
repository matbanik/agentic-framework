"""Input regressions of ``tools/session_wait.py`` (MEU-963, review round 1).

R1-F1: a YAML frontmatter value in single quotes, or with a comment, is the same
value as the plain form, and a value with an open quote does not hold.
R1-F2: a record whose ``state`` is an array or an object is refused by name.
R1-F3: a slug follows ``[A-Za-z0-9][A-Za-z0-9._-]{0,127}``, and no name, slug or
exemption passes with a line break at its end.

The file has its own helpers, so it runs in both trees that carry the tool.
"""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
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

Reply = tuple[int, str, str]


def _tool() -> ModuleType:
    """Import the tool under test."""
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


def _write_front(repo: Path, front: str, *, commit: bool) -> None:
    """Write the demo plan's task.md with the raw frontmatter lines ``front``."""
    path = repo / TASK_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{front}---\n\n# Task\n", encoding="utf-8", newline="\n")
    if commit:
        _git(repo, "add", "--", TASK_REL)
        _git(repo, "commit", "-q", "-m", "task")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repository on ``main`` with one committed file."""
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
    return root


@dataclass
class World:
    """A fake clock, a fake sleep, canned readers and the captured output."""

    mod: ModuleType
    t: float = 0.0
    canned: dict[str, Reply] = field(default_factory=lambda: {})
    lines: list[str] = field(default_factory=lambda: [])

    def clock(self) -> float:
        """The fake monotonic clock."""
        return self.t

    def sleep(self, seconds: float) -> None:
        """Advance the fake clock."""
        self.t += seconds

    def run(
        self, argv: Sequence[str], *, cwd: Path, timeout: float
    ) -> subprocess.CompletedProcess[str]:
        """Answer a canned reader, or pass the command to the tool's real runner."""
        name = Path(argv[1]).name if len(argv) > 1 else Path(argv[0]).name
        reply = self.canned.get(name)
        if reply is not None:
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


def _wait_dir(repo: Path) -> Path:
    return repo / ".git" / "session-wait"


def _record(name: str, state: object) -> dict[str, object]:
    """A wait record of schema ``session-wait/1`` with the given ``state`` value."""
    return {
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


def _put_record(repo: Path, record: dict[str, object]) -> None:
    folder = _wait_dir(repo)
    folder.mkdir(parents=True, exist_ok=True)
    text = json.dumps(record, indent=2) + "\n"
    (folder / f"{record['name']}.json").write_text(text, encoding="utf-8", newline="\n")


def _wait_args(repo: Path, name: str, plan: str, *conds: str) -> list[str]:
    args = ["--repo", str(repo), "wait", "--name", name, "--plan", plan]
    args += ["--owner", "sess-1"]
    for cond in conds:
        args += ["--cond", cond]
    return args + list(DIRECTION) + ["--stable-s", "0"]


# --- R1-F1: frontmatter values ----------------------------------------------------


@pytest.mark.parametrize(
    "front",
    [
        "status: 'in_progress'\n",
        "status: in_progress\n",
        'status: "in_progress"   # the plan runs\n',
        "status: 'in_progress' # the plan runs\n",
        "status:   in_progress   # the plan runs\n",
    ],
)
def test_ag8_r1_f1_plan_idle_reads_each_yaml_form_of_in_progress(
    repo: Path, front: str
) -> None:
    _write_front(repo, front + "stop_gate: 'armed'\n", commit=False)
    world = _world()
    code = world.call("--repo", str(repo), "check", "--cond", f"plan_idle:{SLUG}")
    assert code == 1
    assert world.lines == [f"wait plan_idle:{SLUG}:in_progress"]


@pytest.mark.parametrize(
    "front",
    ["status: 'approved'\n", "status: approved # parked\n", "status: 'it''s done'\n"],
)
def test_ag8_r1_f1_plan_idle_holds_for_quoted_other_statuses(
    repo: Path, front: str
) -> None:
    _write_front(repo, front, commit=False)
    world = _world()
    code = world.call("--repo", str(repo), "check", "--cond", f"plan_idle:{SLUG}")
    assert code == 0
    assert world.lines == ["hold"]


@pytest.mark.parametrize(
    "front",
    [
        "status: 'in_progress\n",
        'status: "in_progress\n',
        "status: 'in_progress' trailing\n",
        "status: ''\n",
    ],
)
def test_ag8_r1_f1_plan_idle_with_a_broken_value_does_not_hold(
    repo: Path, front: str
) -> None:
    _write_front(repo, front, commit=False)
    world = _world()
    code = world.call("--repo", str(repo), "check", "--cond", f"plan_idle:{SLUG}")
    assert code == 1
    assert world.lines == [f"wait plan_idle:{SLUG}:unreadable"]


def _done_world() -> World:
    world = _world()
    status = {"done": True, "enabled": True, "reasons": [], "result": "status"}
    preflight = {"ok": True, "missing": [], "details": {}}
    world.canned = {
        "run_parameters.py": (0, json.dumps(status) + "\n", ""),
        "completion_preflight.py": (0, json.dumps(preflight) + "\n", ""),
    }
    return world


def test_ag8_r1_f1_plan_done_reads_single_quoted_landed_values(repo: Path) -> None:
    _write_front(repo, "status: 'complete'\nstop_gate: 'released:done'\n", commit=True)
    world = _done_world()
    code = world.call("--repo", str(repo), "check", "--cond", f"plan_done:{SLUG}")
    assert code == 0
    assert world.lines == ["hold"]


def test_ag8_r1_f1_plan_done_reads_commented_landed_values(repo: Path) -> None:
    _write_front(
        repo,
        'status: "complete"  # closed\nstop_gate: released:done # sealed\n',
        commit=True,
    )
    world = _done_world()
    code = world.call("--repo", str(repo), "check", "--cond", f"plan_done:{SLUG}")
    assert code == 0
    assert world.lines == ["hold"]


def test_ag8_r1_f1_plan_done_open_quote_is_not_landed(repo: Path) -> None:
    _write_front(repo, "status: 'complete\nstop_gate: 'released:done'\n", commit=True)
    world = _done_world()
    code = world.call("--repo", str(repo), "check", "--cond", f"plan_done:{SLUG}")
    assert code == 1
    assert world.lines == [f"wait plan_done:{SLUG}:not_landed"]


# --- R1-F2: a record state of the wrong type ---------------------------------------


@pytest.mark.parametrize("state", [["armed"], {"armed": True}, [], {}])
def test_ag8_r1_f2_list_shows_a_record_with_a_container_state_as_unreadable(
    repo: Path, state: object
) -> None:
    _put_record(repo, _record("odd", state))
    world = _world()
    assert world.call("--repo", str(repo), "list") == 0
    assert world.lines == ["odd unreadable"]
    world2 = _world()
    assert world2.call("--repo", str(repo), "list", "--json") == 0
    assert json.loads("\n".join(world2.lines)) == [
        {"name": "odd", "state": "unreadable"}
    ]


@pytest.mark.parametrize("state", [["armed"], {"armed": True}])
def test_ag8_r1_f2_wait_refuses_a_record_with_a_container_state_by_name(
    repo: Path, state: object
) -> None:
    _put_record(repo, _record("odd", state))
    world = _world()
    assert world.call(*_wait_args(repo, "odd", SLUG, "paths_clean:src")) == 1
    assert world.lines == ["wait_refused:record_unreadable:odd"]


@pytest.mark.parametrize("state", [["fired"], {"fired": True}])
def test_ag8_r1_f2_use_refuses_a_record_with_a_container_state_by_name(
    repo: Path, state: object
) -> None:
    _put_record(repo, _record("odd", state))
    world = _world()
    assert world.call("--repo", str(repo), "use", "--name", "odd") == 1
    assert world.lines == ["use_refused:record_unreadable:odd"]


# --- R1-F3: the slug grammar and a line break at the end ---------------------------


@pytest.mark.parametrize(
    "slug", ["2026-11-13-release.v1", "a", "A_b.c-d", "a" + "b" * 127]
)
def test_ag8_r1_f3_check_accepts_each_slug_of_the_grammar(
    repo: Path, slug: str
) -> None:
    world = _world()
    code = world.call("--repo", str(repo), "check", "--cond", f"plan_idle:{slug}")
    assert code == 1
    assert world.lines == [f"wait plan_idle:{slug}:no_task"]


def test_ag8_r1_f3_wait_arms_a_dotted_plan(repo: Path) -> None:
    world = _world()
    code = world.call(
        *_wait_args(repo, "dotted", "2026-11-13-release.v1", "paths_clean:src")
    )
    assert code == 0
    data = json.loads((_wait_dir(repo) / "dotted.json").read_text(encoding="utf-8"))
    assert data["plan"] == "2026-11-13-release.v1"
    assert data["state"] == "fired"


@pytest.mark.parametrize(
    "slug", ["a" + "b" * 128, ".hidden", "-dash", "a/b", "a b", "demo\n", "demo\r"]
)
def test_ag8_r1_f3_check_refuses_a_slug_outside_the_grammar(
    repo: Path, slug: str
) -> None:
    world = _world()
    code = world.call("--repo", str(repo), "check", "--cond", f"plan_idle:{slug}")
    assert code == 2
    assert world.lines == [f"usage_error:bad_slug:{slug}"]


@pytest.mark.parametrize("plan", ["a" + "b" * 128, "demo\n"])
def test_ag8_r1_f3_wait_refuses_a_plan_outside_the_grammar(
    repo: Path, plan: str
) -> None:
    world = _world()
    assert world.call(*_wait_args(repo, "named", plan, "paths_clean:src")) == 2
    assert world.lines == [f"usage_error:bad_slug:{plan}"]
    assert not _wait_dir(repo).exists()


def test_ag8_r1_f3_a_name_with_a_line_break_is_refused(repo: Path) -> None:
    world = _world()
    assert world.call(*_wait_args(repo, "named\n", SLUG, "paths_clean:src")) == 2
    assert world.lines == ["usage_error:bad_name:named\n"]
    world2 = _world()
    assert world2.call("--repo", str(repo), "use", "--name", "named\n") == 2
    assert world2.lines == ["usage_error:bad_name:named\n"]
    assert not _wait_dir(repo).exists()


def test_ag8_r1_f3_an_exemption_with_a_line_break_is_refused(repo: Path) -> None:
    world = _world()
    code = world.call(
        "--repo", str(repo), "check", "--cond", "lanes_free", "--exempt", "lane-a:D-7\n"
    )
    assert code == 2
    assert world.lines == ["usage_error:bad_exempt:lane-a:D-7\n"]
