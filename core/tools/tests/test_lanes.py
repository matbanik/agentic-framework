"""MEU-784 AC-784.2–10: lane cards, admission, ownership paths — red first (G19).

FIC: ``docs/execution/plans/2026-10-20-multi-agent-lanes/implementation-plan.md``
§MEU-784 (AC-784.2–AC-784.10; design §5.2 "Lane cards", §5.3 "Ownership in the
plan", §5.7 "Messages and halts"; decisions D-P8, D-P9, D-P10, D-P13, D-P14).

CLI contract pinned here (EA-8): a refusal prints ``refused: <reason>`` on stdout
and exits 1; ``beat`` exits 3 and prints ``halt`` under ``lanes/HALT``; ``beat``
and ``release`` name the lane by ``--plan`` (the lane slug is the plan folder
name), because ``release`` runs after the lane worktree is gone (D-P9).

Every CLI test runs in a disposable repository in ``tmp_path`` with two linked
worktrees, with system and global git config cut off. Registry-lock holders are
separate processes with this file's own copy of the lock protocol. Waits are
injected (``wait_s=0.2``, ``poll_s=0.01``); staleness uses an injected ``now``
or backdated cards. Do not skip, only, or early-return (G36).
"""

from __future__ import annotations

import importlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Iterator

import pytest

ROOT = Path(__file__).resolve().parents[2]
LANES = ROOT / "tools" / "lanes.py"
WAIT_S = 0.2
POLL_S = 0.01
CLI_TIMEOUT_S = 120
# `list` takes no lock: it must finish well inside REGISTRY_WAIT_S (10 s).
LIST_MAX_S = 5.0
HEX16 = re.compile(r"[0-9a-f]{16}")
UTC_Z = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")
PLANS = "docs/execution/plans"

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
HOLDER_BODY = '{"pid": {pid}, "argv": ["holder.py", "claim", "--plan", "x"]}'

# Committed in every fixture repository: (plan slug, owns, must_not_touch); None = no section.
FIXTURE_PLANS: dict[str, tuple[list[str], list[str]] | None] = {
    "2026-10-20-lane-a": (["src/"], ["docs/x.md"]),
    "2026-10-20-lane-b": (["docs/new.md"], []),
    "2026-10-20-lane-c": (["src/a.py"], []),
    "2026-10-20-lane-d": (["other/"], []),
    "2026-10-20-lane-none": None,
    "2026-10-20-lane-jf": ([".agent/context/meu-status.yaml"], []),
    "2026-10-20-lane-jd": ([".agent/"], []),
    "2026-10-20-lane-contra": (["a/"], ["a/b.py"]),
    "2026-10-20-lane-jt": (["tools/"], []),
}
# Design §2.4, §9.2: the fixture project's junction files, its worktree-config data (D-P10).
FIXTURE_JUNCTION_FILES = (
    ".agent/context/known-issues.yaml",
    ".agent/context/meu-status.yaml",
    ".agent/context/meu-registry.md",
    ".agent/context/known-issues.md",
    "docs/BUILD_PLAN.md",
    ".agent/context/current-focus.md",
    "docs/execution/metrics.md",
    ".secrets.baseline",
    "tools/temp_citation_baseline.json",
)
WORKTREE_CONFIG = ".agent/credits/worktree.json"
WORKTREE_CONFIG_DATA = {
    "env_files": [],
    "frozen_dirs": [],
    "venv_build": None,
    "linked_trees": [],
    "junction_files": list(FIXTURE_JUNCTION_FILES),
}
FIXTURE_FILES = {
    "tools/a.py": "A = 1\n",
    "tools/b.py": "B = 1\n",
    "src/a.py": "A = 1\n",
    "docs/x.md": "# x\n",
    "other/o.py": "O = 1\n",
    ".agent/context/meu-status.yaml": "meus: []\n",
    WORKTREE_CONFIG: json.dumps(WORKTREE_CONFIG_DATA) + "\n",
}


def _lanes() -> ModuleType:
    return importlib.import_module("tools.lanes")


def _task_text(ownership: tuple[list[str], list[str]] | None) -> str:
    head = "---\nproject: fixture\n---\n\n# Task\n\n| # | Task |\n|---|---|\n| 1 | work |\n"
    if ownership is None:
        return head
    owns, mnt = ownership

    def block(key: str, items: list[str]) -> str:
        if not items:
            return f"{key}: []\n"
        return f"{key}:\n" + "".join(f"  - {item}\n" for item in items)

    return (
        head
        + "\n## Lane Ownership\n\n```yaml\n"
        + block("owns", owns)
        + block("must_not_touch", mnt)
        + "```\n"
    )


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


@dataclass
class LaneRepo:
    main: Path
    wt1: Path
    wt2: Path
    common: Path
    base: str

    @property
    def lanes_dir(self) -> Path:
        return self.common / "lanes"

    def card_path(self, slug: str) -> Path:
        return self.lanes_dir / f"{slug}.json"

    def card(self, slug: str) -> dict[str, Any]:
        return json.loads(self.card_path(slug).read_text(encoding="utf-8"))


@pytest.fixture
def lane_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LaneRepo:
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
    monkeypatch.delenv(_lanes().SESSION_ENV, raising=False)
    main = tmp_path / "repo"
    main.mkdir()
    _git(main, "init", "-q", "-b", "main")
    _git(main, "config", "core.autocrlf", "false")
    for rel, text in FIXTURE_FILES.items():
        _write(main / rel, text)
    for slug, ownership in FIXTURE_PLANS.items():
        _write(main / PLANS / slug / "task.md", _task_text(ownership))
    _git(main, "add", "-A")
    _git(main, "commit", "-q", "-m", "fixture")
    base = _git(main, "rev-parse", "HEAD").strip()
    wt1 = tmp_path / "wt1"
    wt2 = tmp_path / "wt2"
    _git(main, "worktree", "add", "-q", "--detach", str(wt1))
    _git(main, "worktree", "add", "-q", "--detach", str(wt2))
    common = Path(
        _git(main, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    ).resolve()
    return LaneRepo(
        main=main.resolve(),
        wt1=wt1.resolve(),
        wt2=wt2.resolve(),
        common=common,
        base=base,
    )


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


def _claim(
    repo: LaneRepo, wt: Path, slug: str, session: str
) -> subprocess.CompletedProcess[str]:
    return _run(
        wt,
        "claim",
        "--plan",
        f"{PLANS}/{slug}",
        "--worktree",
        str(wt),
        "--session",
        session,
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


def _utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _card_dict(worktree: Path, /, **over: Any) -> dict[str, Any]:
    # Positional-only, so a case can override the ``worktree`` field by keyword.
    card: dict[str, Any] = {
        "lane": "2026-10-20-lane-x",
        "generation": "0123456789abcdef",
        "session": "s-one",
        "state": "active",
        "op": None,
        "worktree": worktree.resolve().as_posix(),
        "branch": None,
        "plan": f"{PLANS}/2026-10-20-lane-x/",
        "owns": ["tools/"],
        "claims": [],
        "gates": [],
        "updated": _utc(datetime.now(timezone.utc)),
    }
    card.update(over)
    return card


def _put_card(lanes_dir: Path, card: dict[str, Any]) -> Path:
    lanes_dir.mkdir(parents=True, exist_ok=True)
    path = lanes_dir / f"{card['lane']}.json"
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
        # The holder reports its own pid: under a venv launcher (uv on Windows)
        # sys.executable is a trampoline whose child is the real interpreter,
        # so Popen.pid is not the process that holds the lock.
        word, _, pid = line.partition(" ")
        assert word == "held" and pid.isdigit(), line
        self._pid = int(pid)

    @property
    def pid(self) -> int:
        return self._pid

    def stop(self) -> None:
        if self.proc.poll() is None:
            assert self.proc.stdin is not None
            self.proc.stdin.close()
            self.proc.wait(timeout=30)


@pytest.fixture
def holders() -> Iterator[list[_Holder]]:
    held: list[_Holder] = []
    yield held
    for h in held:
        h.stop()


def _make_dir_link(link: Path, target: Path) -> None:
    """A directory link without privileges: a junction on Windows, a symlink elsewhere."""
    target.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)


# ---------------------------------------------------------------------------
# Constants (Constant Classification; D-P10, D-P13)
# ---------------------------------------------------------------------------


def test_ac784_3_constants_and_junction_files() -> None:
    lanes = _lanes()
    assert lanes.STALE_S == 21600
    assert lanes.REGISTRY_WAIT_S == 10.0
    assert lanes.POLL_S == 0.05
    assert lanes.JUNCTION_KEY == "junction_files"
    assert lanes.SESSION_ENV.endswith("_SESSION")


def test_ac784_20_junction_files_come_from_the_worktree_config(
    lane_repo: LaneRepo,
) -> None:
    assert _lanes().junction_files(lane_repo.main) == FIXTURE_JUNCTION_FILES


def test_ac784_20_config_without_junction_files_refuses_claim(
    lane_repo: LaneRepo,
) -> None:
    data = {k: v for k, v in WORKTREE_CONFIG_DATA.items() if k != "junction_files"}
    _write(lane_repo.wt1 / WORKTREE_CONFIG, json.dumps(data) + "\n")
    _refused(
        _claim(lane_repo, lane_repo.wt1, "2026-10-20-lane-a", "s-one"),
        "worktree_bad:config",
    )
    assert not lane_repo.card_path("2026-10-20-lane-a").exists()


def test_ac784_20_an_empty_junction_list_admits_the_former_junction_owner(
    lane_repo: LaneRepo,
) -> None:
    # No project defaults (design §9.2): a project that lists no junction file has none.
    _write(
        lane_repo.wt1 / WORKTREE_CONFIG,
        json.dumps({**WORKTREE_CONFIG_DATA, "junction_files": []}) + "\n",
    )
    _ok(_claim(lane_repo, lane_repo.wt1, "2026-10-20-lane-jf", "s-one"))


# ---------------------------------------------------------------------------
# AC-784.2: cards are read and written only through _load_card / _write_card
# ---------------------------------------------------------------------------


def test_ac784_2_load_card_accepts_a_valid_card(tmp_path: Path) -> None:
    lanes = _lanes()
    card = _card_dict(tmp_path)
    path = _put_card(tmp_path / "lanes", card)
    assert lanes._load_card(path) == card
    landing = _card_dict(tmp_path, state="landing", op="op-1", branch="lane/x")
    assert lanes._load_card(_put_card(tmp_path / "lanes", landing)) == landing


def test_ac784_2_load_card_refuses_each_bad_field(tmp_path: Path) -> None:
    lanes = _lanes()
    cases: list[tuple[str, dict[str, Any] | None, str | None]] = [
        ("card_bad:session", None, "session"),
        ("card_bad:extra", {"extra": 1}, None),
        ("card_bad:generation", {"generation": "8f3c1e2a"}, None),
        ("card_bad:generation", {"generation": "G" * 16}, None),
        ("card_bad:generation", {"generation": "0123456789ABCDEF"}, None),
        ("card_bad:state", {"state": "done"}, None),
        ("card_bad:lane", {"lane": "Lane_A"}, None),
        ("card_bad:op", {"op": "op-1"}, None),
        ("card_bad:op", {"state": "landing", "op": None}, None),
        ("card_bad:worktree", {"worktree": "relative/path"}, None),
        ("card_bad:owns", {"owns": "tools/"}, None),
        ("card_bad:claims", {"claims": [1]}, None),
        ("card_bad:gates", {"gates": "none"}, None),
        ("card_bad:updated", {"updated": "2026-10-21T01:02:03"}, None),
        ("card_bad:branch", {"branch": 5}, None),
        ("card_bad:session", {"session": ""}, None),
        ("card_bad:plan", {"plan": 7}, None),
    ]
    for reason, over, drop in cases:
        card = _card_dict(tmp_path, **(over or {}))
        if drop is not None:
            del card[drop]
        path = _put_card(tmp_path / "lanes", card)
        with pytest.raises(lanes.Refusal) as caught:
            lanes._load_card(path)
        assert caught.value.reason == reason, (reason, over, drop, caught.value.reason)
    bad = tmp_path / "lanes" / "2026-10-20-broken.json"
    bad.write_text("{", encoding="utf-8")
    with pytest.raises(lanes.Refusal) as caught:
        lanes._load_card(bad)
    assert caught.value.reason.startswith("card_bad")


def test_ac784_2_stale_generation_is_superseded_and_bytes_unchanged(
    tmp_path: Path,
) -> None:
    lanes = _lanes()
    common = tmp_path / "common"
    card = _card_dict(tmp_path, generation="1111111111111111")
    lanes._write_card(common, card, expect=None, wait_s=WAIT_S, poll_s=POLL_S)
    path = common / "lanes" / f"{card['lane']}.json"
    before = path.read_bytes()
    stale = dict(card, updated=_utc(datetime.now(timezone.utc) + timedelta(seconds=5)))
    with pytest.raises(lanes.Refusal) as caught:
        lanes._write_card(
            common,
            stale,
            expect={"session": "s-one", "generation": "0000000000000000", "op": None},
            wait_s=WAIT_S,
            poll_s=POLL_S,
        )
    assert caught.value.reason == "card_superseded"
    assert path.read_bytes() == before


def test_ac784_2_wrong_session_or_op_is_superseded(tmp_path: Path) -> None:
    lanes = _lanes()
    common = tmp_path / "common"
    card = _card_dict(tmp_path)
    lanes._write_card(common, card, expect=None, wait_s=WAIT_S, poll_s=POLL_S)
    path = common / "lanes" / f"{card['lane']}.json"
    before = path.read_bytes()
    for expect in (
        {"session": "s-two", "generation": card["generation"], "op": None},
        {"session": "s-one", "generation": card["generation"], "op": "op-9"},
    ):
        with pytest.raises(lanes.Refusal) as caught:
            lanes._write_card(
                common,
                dict(card, owns=["docs/"]),
                expect=expect,
                wait_s=WAIT_S,
                poll_s=POLL_S,
            )
        assert caught.value.reason == "card_superseded", expect
        assert path.read_bytes() == before
    # The matching expectation writes.
    lanes._write_card(
        common,
        dict(card, owns=["docs/"]),
        expect={"session": "s-one", "generation": card["generation"], "op": None},
        wait_s=WAIT_S,
        poll_s=POLL_S,
    )
    assert lanes._load_card(path)["owns"] == ["docs/"]


def test_ac784_2_create_refuses_over_a_reserving_card_and_replaces_a_released_one(
    tmp_path: Path,
) -> None:
    lanes = _lanes()
    common = tmp_path / "common"
    card = _card_dict(tmp_path)
    lanes._write_card(common, card, expect=None, wait_s=WAIT_S, poll_s=POLL_S)
    fresh = dict(card, generation="2222222222222222", session="s-two")
    with pytest.raises(lanes.Refusal) as caught:
        lanes._write_card(common, fresh, expect=None, wait_s=WAIT_S, poll_s=POLL_S)
    assert caught.value.reason == "claim_reserved"
    released = dict(card, state="released")
    lanes._write_card(
        common,
        released,
        expect={"session": "s-one", "generation": card["generation"], "op": None},
        wait_s=WAIT_S,
        poll_s=POLL_S,
    )
    lanes._write_card(common, fresh, expect=None, wait_s=WAIT_S, poll_s=POLL_S)
    assert (
        lanes._load_card(common / "lanes" / f"{card['lane']}.json")["generation"]
        == "2222222222222222"
    )


def test_ac784_2_write_goes_through_a_temporary_file_and_os_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lanes = _lanes()
    common = tmp_path / "common"
    card = _card_dict(tmp_path)
    calls: list[tuple[Path, Path]] = []
    real_replace = os.replace

    def recording_replace(src: Any, dst: Any) -> None:
        calls.append((Path(src), Path(dst)))
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", recording_replace)
    lanes._write_card(common, card, expect=None, wait_s=WAIT_S, poll_s=POLL_S)
    target = common / "lanes" / f"{card['lane']}.json"
    assert len(calls) == 1
    src, dst = calls[0]
    assert dst.resolve() == target.resolve()
    assert src.parent.resolve() == target.parent.resolve()
    assert src != dst
    assert not src.exists()
    assert lanes._load_card(target) == card


def test_ac784_2_write_takes_the_registry_lock(
    tmp_path: Path, holders: list[_Holder]
) -> None:
    lanes = _lanes()
    common = tmp_path / "common"
    holder = _Holder(common / "lanes" / "registry.lock")
    holders.append(holder)
    card = _card_dict(tmp_path)
    with pytest.raises(lanes.Refusal) as caught:
        lanes._write_card(common, card, expect=None, wait_s=WAIT_S, poll_s=POLL_S)
    assert caught.value.reason == "registry_busy"
    assert not (common / "lanes" / f"{card['lane']}.json").exists()
    holder.stop()
    lanes._write_card(common, card, expect=None, wait_s=WAIT_S, poll_s=POLL_S)
    assert (common / "lanes" / "registry.lock").is_file()


# ---------------------------------------------------------------------------
# AC-784.3: claim and its refusals
# ---------------------------------------------------------------------------


def test_ac784_3_claim_writes_an_active_card(lane_repo: LaneRepo) -> None:
    before = datetime.now(timezone.utc).replace(microsecond=0)
    out = _ok(_claim(lane_repo, lane_repo.wt1, "2026-10-20-lane-a", "s-one"))
    card = lane_repo.card("2026-10-20-lane-a")
    assert set(card) == {
        "lane",
        "generation",
        "session",
        "state",
        "op",
        "worktree",
        "branch",
        "plan",
        "owns",
        "claims",
        "gates",
        "updated",
    }
    assert card["lane"] == "2026-10-20-lane-a"
    assert HEX16.fullmatch(card["generation"])
    assert card["session"] == "s-one"
    assert card["state"] == "active"
    assert card["op"] is None
    assert card["worktree"] == lane_repo.wt1.as_posix()
    assert card["branch"] is None
    assert card["plan"] == f"{PLANS}/2026-10-20-lane-a/"
    assert card["owns"] == ["src/"]
    assert card["claims"] == [] and card["gates"] == []
    assert UTC_Z.fullmatch(card["updated"])
    updated = datetime.strptime(card["updated"], "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )
    assert (
        before - timedelta(seconds=1)
        <= updated
        <= datetime.now(timezone.utc) + timedelta(seconds=1)
    )
    assert (
        f"claimed 2026-10-20-lane-a generation={card['generation']}" in out.splitlines()
    )


def test_ac784_3_two_claims_get_distinct_generations(lane_repo: LaneRepo) -> None:
    _ok(_claim(lane_repo, lane_repo.wt1, "2026-10-20-lane-a", "s-one"))
    _ok(_claim(lane_repo, lane_repo.wt2, "2026-10-20-lane-b", "s-two"))
    assert (
        lane_repo.card("2026-10-20-lane-a")["generation"]
        != lane_repo.card("2026-10-20-lane-b")["generation"]
    )


def test_ac784_3_session_comes_from_the_environment(lane_repo: LaneRepo) -> None:
    proc = _run(
        lane_repo.wt1,
        "claim",
        "--plan",
        f"{PLANS}/2026-10-20-lane-a",
        "--worktree",
        str(lane_repo.wt1),
        env={_lanes().SESSION_ENV: "s-env"},
    )
    _ok(proc)
    assert lane_repo.card("2026-10-20-lane-a")["session"] == "s-env"


def test_ac784_3_no_session_is_refused(lane_repo: LaneRepo) -> None:
    proc = _run(
        lane_repo.wt1,
        "claim",
        "--plan",
        f"{PLANS}/2026-10-20-lane-a",
        "--worktree",
        str(lane_repo.wt1),
    )
    _refused(proc, "no_session")
    assert not lane_repo.card_path("2026-10-20-lane-a").exists()


def test_ac784_3_same_canonical_worktree_is_reserved(lane_repo: LaneRepo) -> None:
    _ok(_claim(lane_repo, lane_repo.wt1, "2026-10-20-lane-a", "s-one"))
    other_spelling = lane_repo.wt2 / ".." / "wt1"
    proc = _run(
        lane_repo.wt2,
        "claim",
        "--plan",
        f"{PLANS}/2026-10-20-lane-d",
        "--worktree",
        str(other_spelling),
        "--session",
        "s-two",
    )
    _refused(proc, "worktree_reserved")
    assert not lane_repo.card_path("2026-10-20-lane-d").exists()


def test_ac784_3_duplicate_lane_claim_is_reserved(lane_repo: LaneRepo) -> None:
    _ok(_claim(lane_repo, lane_repo.wt1, "2026-10-20-lane-a", "s-one"))
    before = lane_repo.card_path("2026-10-20-lane-a").read_bytes()
    _refused(
        _claim(lane_repo, lane_repo.wt2, "2026-10-20-lane-a", "s-two"), "claim_reserved"
    )
    assert lane_repo.card_path("2026-10-20-lane-a").read_bytes() == before


def test_ac784_3_overlapping_owns_names_the_lane_and_path(lane_repo: LaneRepo) -> None:
    _ok(_claim(lane_repo, lane_repo.wt1, "2026-10-20-lane-a", "s-one"))
    _refused(
        _claim(lane_repo, lane_repo.wt2, "2026-10-20-lane-c", "s-two"),
        "owns_overlap:2026-10-20-lane-a:src/a.py",
    )


def test_ac784_3_stale_reserving_card_names_the_human_step(lane_repo: LaneRepo) -> None:
    old = _utc(datetime.now(timezone.utc) - timedelta(hours=7))
    stale = _card_dict(
        lane_repo.wt1,
        lane="2026-10-20-other",
        session="s-zzz",
        owns=["zzz/"],
        updated=old,
    )
    _put_card(lane_repo.lanes_dir, stale)
    out = _refused(
        _claim(lane_repo, lane_repo.wt1, "2026-10-20-lane-a", "s-one"),
        "stale_reserving:2026-10-20-other",
    )
    assert "human" in out.lower()
    assert "2026-10-20-other.json" in out


def test_ac784_3_owns_a_junction_file_is_refused(lane_repo: LaneRepo) -> None:
    _refused(
        _claim(lane_repo, lane_repo.wt1, "2026-10-20-lane-jf", "s-one"),
        "owns_junction:.agent/context/meu-status.yaml",
    )
    _refused(
        _claim(lane_repo, lane_repo.wt2, "2026-10-20-lane-jd", "s-two"),
        "owns_junction:.agent/",
    )
    assert not lane_repo.card_path("2026-10-20-lane-jf").exists()
    assert not lane_repo.card_path("2026-10-20-lane-jd").exists()


def test_ac784_3_owns_a_folder_that_could_hold_a_junction_file_is_refused(
    lane_repo: LaneRepo,
) -> None:
    # R1-F3: a folder over a junction path is refused even when the file is not there
    # yet, because the lane could create it.
    assert not (lane_repo.wt1 / "tools/temp_citation_baseline.json").exists()
    _refused(
        _claim(lane_repo, lane_repo.wt1, "2026-10-20-lane-jt", "s-one"),
        "owns_junction:tools/",
    )
    assert not lane_repo.card_path("2026-10-20-lane-jt").exists()


def test_ac784_3_unwritable_common_dir_is_refused(lane_repo: LaneRepo) -> None:
    # A plain file where the lanes directory belongs: nothing can be written there.
    lane_repo.lanes_dir.write_text("not a directory\n", encoding="utf-8")
    _refused(
        _claim(lane_repo, lane_repo.wt1, "2026-10-20-lane-a", "s-one"),
        "common_dir_unwritable",
    )


def test_ac784_3_a_released_card_reserves_nothing(lane_repo: LaneRepo) -> None:
    _ok(_claim(lane_repo, lane_repo.main, "2026-10-20-lane-b", "s-one"))
    first = lane_repo.card("2026-10-20-lane-b")["generation"]
    _ok(
        _run(
            lane_repo.main,
            "release",
            "--plan",
            f"{PLANS}/2026-10-20-lane-b",
            "--session",
            "s-one",
        )
    )
    _ok(_claim(lane_repo, lane_repo.main, "2026-10-20-lane-b", "s-two"))
    card = lane_repo.card("2026-10-20-lane-b")
    assert card["state"] == "active" and card["session"] == "s-two"
    assert card["generation"] != first


def test_ac784_3_reservation_conflict_rules(tmp_path: Path) -> None:
    lanes = _lanes()
    now = datetime.now(timezone.utc)
    wt_a = tmp_path / "a"
    wt_b = tmp_path / "b"
    new = _card_dict(
        wt_b,
        lane="2026-10-20-new",
        owns=["docs/"],
        branch="lane/x",
        claims=["port:8765"],
    )

    def other(**over: Any) -> dict[str, Any]:
        base: dict[str, Any] = {
            "lane": "2026-10-20-old",
            "session": "s-old",
            "owns": ["zzz/"],
            "claims": [],
        }
        base.update(over)
        return _card_dict(wt_a, **base)

    conflict = lanes._reservation_conflict
    assert (
        conflict(new, [other(branch="lane/x")], now=now, ignorecase=False)
        == "branch_reserved"
    )
    assert (
        conflict(
            dict(new, branch=None), [other(branch=None)], now=now, ignorecase=False
        )
        is None
    )
    assert (
        conflict(new, [other(claims=["port:8765"])], now=now, ignorecase=False)
        == "claim_reserved"
    )
    assert (
        conflict(new, [other(owns=["docs/a.md"])], now=now, ignorecase=False)
        == "owns_overlap:2026-10-20-old:docs/"
    )
    assert (
        conflict(
            new, [other(worktree=wt_b.resolve().as_posix())], now=now, ignorecase=False
        )
        == "worktree_reserved"
    )
    # Released cards reserve nothing; landing cards reserve like active ones.
    assert (
        conflict(
            new, [other(branch="lane/x", state="released")], now=now, ignorecase=False
        )
        is None
    )
    assert (
        conflict(
            new,
            [other(branch="lane/x", state="landing", op="op-1")],
            now=now,
            ignorecase=False,
        )
        == "branch_reserved"
    )
    # A stale conflicting card refuses as stale, for the human.
    old = _utc(now - timedelta(seconds=21601))
    assert (
        conflict(new, [other(branch="lane/x", updated=old)], now=now, ignorecase=False)
        == "stale_reserving:2026-10-20-old"
    )
    # Case folding applies to owns when core.ignorecase is true.
    assert conflict(new, [other(owns=["DOCS/"])], now=now, ignorecase=False) is None
    assert (
        conflict(new, [other(owns=["DOCS/"])], now=now, ignorecase=True)
        == "owns_overlap:2026-10-20-old:docs/"
    )


# ---------------------------------------------------------------------------
# AC-784.4: beat
# ---------------------------------------------------------------------------


def _backdate(repo: LaneRepo, slug: str, hours: float) -> str:
    card = repo.card(slug)
    card["updated"] = _utc(datetime.now(timezone.utc) - timedelta(hours=hours))
    repo.card_path(slug).write_text(json.dumps(card), encoding="utf-8")
    return card["updated"]


def test_ac784_4_beat_updates_updated_under_the_cas(lane_repo: LaneRepo) -> None:
    _ok(_claim(lane_repo, lane_repo.wt1, "2026-10-20-lane-a", "s-one"))
    generation = lane_repo.card("2026-10-20-lane-a")["generation"]
    old = _backdate(lane_repo, "2026-10-20-lane-a", 2)
    _ok(
        _run(
            lane_repo.wt1,
            "beat",
            "--plan",
            f"{PLANS}/2026-10-20-lane-a",
            "--session",
            "s-one",
        )
    )
    card = lane_repo.card("2026-10-20-lane-a")
    assert card["updated"] != old
    updated = datetime.strptime(card["updated"], "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )
    assert datetime.now(timezone.utc) - updated < timedelta(minutes=5)
    assert card["generation"] == generation and card["state"] == "active"
    # With the generation the claim printed, the beat also matches.
    _ok(
        _run(
            lane_repo.wt1,
            "beat",
            "--plan",
            f"{PLANS}/2026-10-20-lane-a",
            "--session",
            "s-one",
            "--generation",
            generation,
        )
    )


def test_ac784_4_beat_by_another_session_or_generation_is_superseded(
    lane_repo: LaneRepo,
) -> None:
    _ok(_claim(lane_repo, lane_repo.wt1, "2026-10-20-lane-a", "s-one"))
    before = lane_repo.card_path("2026-10-20-lane-a").read_bytes()
    _refused(
        _run(
            lane_repo.wt1,
            "beat",
            "--plan",
            f"{PLANS}/2026-10-20-lane-a",
            "--session",
            "s-two",
        ),
        "card_superseded",
    )
    _refused(
        _run(
            lane_repo.wt1,
            "beat",
            "--plan",
            f"{PLANS}/2026-10-20-lane-a",
            "--session",
            "s-one",
            "--generation",
            "ffffffffffffffff",
        ),
        "card_superseded",
    )
    assert lane_repo.card_path("2026-10-20-lane-a").read_bytes() == before


def test_ac784_4_halt_after_claim_stops_the_next_beat(lane_repo: LaneRepo) -> None:
    _ok(_claim(lane_repo, lane_repo.wt1, "2026-10-20-lane-a", "s-one"))
    _backdate(lane_repo, "2026-10-20-lane-a", 1)
    before = lane_repo.card_path("2026-10-20-lane-a").read_bytes()
    (lane_repo.lanes_dir / "HALT").write_text("stop\n", encoding="utf-8")
    proc = _run(
        lane_repo.wt1,
        "beat",
        "--plan",
        f"{PLANS}/2026-10-20-lane-a",
        "--session",
        "s-one",
    )
    assert proc.returncode == 3, (proc.returncode, proc.stdout, proc.stderr)
    assert "halt" in proc.stdout.splitlines()
    assert lane_repo.card_path("2026-10-20-lane-a").read_bytes() == before


def test_ac784_4_beat_without_a_card_is_refused(lane_repo: LaneRepo) -> None:
    _refused(
        _run(
            lane_repo.wt1,
            "beat",
            "--plan",
            f"{PLANS}/2026-10-20-lane-a",
            "--session",
            "s-one",
        ),
        "no_card",
    )


def test_ac784_4_a_delayed_beat_never_revives_a_released_card(
    lane_repo: LaneRepo,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # R2-F1: the beat reads the card, then a release and an overlapping claim
    # land before its write. The write must not bring the released card back.
    lanes = _lanes()
    monkeypatch.chdir(lane_repo.main)
    plan_a = f"{PLANS}/2026-10-20-lane-a"
    plan_c = f"{PLANS}/2026-10-20-lane-c"
    assert (
        lanes.main(
            [
                "claim",
                "--plan",
                plan_a,
                "--worktree",
                str(lane_repo.main),
                "--session",
                "s-one",
            ]
        )
        == 0
    )
    real = lanes._write_card
    parked: list[bool] = []
    between: list[int] = []

    def interleave(common: Path, card: dict[str, Any], **kwargs: Any) -> Path:
        # Only the beat's own write parks; the writes it schedules pass through.
        if not parked and card["lane"] == "2026-10-20-lane-a":
            parked.append(True)
            between.append(
                lanes.main(["release", "--plan", plan_a, "--session", "s-one"])
            )
            between.append(
                lanes.main(
                    [
                        "claim",
                        "--plan",
                        plan_c,
                        "--worktree",
                        str(lane_repo.main),
                        "--session",
                        "s-two",
                    ]
                )
            )
        return real(common, card, **kwargs)

    monkeypatch.setattr(lanes, "_write_card", interleave)
    capsys.readouterr()
    code = lanes.main(["beat", "--plan", plan_a, "--session", "s-one"])
    out = capsys.readouterr().out
    assert between == [0, 0], out
    assert code == 1, out
    assert any(
        line.startswith("refused: card_superseded") for line in out.splitlines()
    ), out
    assert lane_repo.card("2026-10-20-lane-a")["state"] == "released"
    assert lane_repo.card("2026-10-20-lane-c")["state"] == "active"


# ---------------------------------------------------------------------------
# AC-784.5: release
# ---------------------------------------------------------------------------


def test_ac784_5_release_waits_for_the_linked_worktree_to_go(
    lane_repo: LaneRepo,
) -> None:
    _ok(_claim(lane_repo, lane_repo.wt1, "2026-10-20-lane-a", "s-one"))
    before = lane_repo.card_path("2026-10-20-lane-a").read_bytes()
    _refused(
        _run(
            lane_repo.main,
            "release",
            "--plan",
            f"{PLANS}/2026-10-20-lane-a",
            "--session",
            "s-one",
        ),
        "worktree_live",
    )
    assert lane_repo.card_path("2026-10-20-lane-a").read_bytes() == before
    _git(lane_repo.main, "worktree", "remove", str(lane_repo.wt1))
    _ok(
        _run(
            lane_repo.main,
            "release",
            "--plan",
            f"{PLANS}/2026-10-20-lane-a",
            "--session",
            "s-one",
        )
    )
    card = lane_repo.card("2026-10-20-lane-a")
    assert card["state"] == "released"


def test_ac784_5_a_main_tree_card_releases(lane_repo: LaneRepo) -> None:
    _ok(_claim(lane_repo, lane_repo.main, "2026-10-20-lane-b", "s-one"))
    _ok(
        _run(
            lane_repo.main,
            "release",
            "--plan",
            f"{PLANS}/2026-10-20-lane-b",
            "--session",
            "s-one",
        )
    )
    assert lane_repo.card("2026-10-20-lane-b")["state"] == "released"


def test_ac784_5_release_by_another_session_is_superseded(lane_repo: LaneRepo) -> None:
    _ok(_claim(lane_repo, lane_repo.main, "2026-10-20-lane-b", "s-one"))
    _refused(
        _run(
            lane_repo.main,
            "release",
            "--plan",
            f"{PLANS}/2026-10-20-lane-b",
            "--session",
            "s-two",
        ),
        "card_superseded",
    )
    assert lane_repo.card("2026-10-20-lane-b")["state"] == "active"


# ---------------------------------------------------------------------------
# AC-784.6: list
# ---------------------------------------------------------------------------


def test_ac784_6_is_stale_uses_the_injected_clock(tmp_path: Path) -> None:
    lanes = _lanes()
    now = datetime(2026, 10, 21, 12, 0, 0, tzinfo=timezone.utc)
    at = lambda delta: _card_dict(tmp_path, updated=_utc(now - delta))  # noqa: E731
    assert lanes._is_stale(at(timedelta(hours=6, seconds=1)), now) is True
    assert lanes._is_stale(at(timedelta(hours=6)), now) is False
    assert lanes._is_stale(at(timedelta(hours=1)), now) is False


def test_ac784_6_list_marks_stale_cards_and_halt(lane_repo: LaneRepo) -> None:
    _ok(_claim(lane_repo, lane_repo.wt1, "2026-10-20-lane-a", "s-one"))
    _ok(_claim(lane_repo, lane_repo.wt2, "2026-10-20-lane-b", "s-two"))
    old = _utc(datetime.now(timezone.utc) - timedelta(hours=6, seconds=1))
    card = lane_repo.card("2026-10-20-lane-a")
    card["updated"] = old
    lane_repo.card_path("2026-10-20-lane-a").write_text(
        json.dumps(card), encoding="utf-8"
    )
    text = _ok(_run(lane_repo.main, "list"))
    lines = text.splitlines()
    line_a = [line for line in lines if line.startswith("2026-10-20-lane-a ")]
    line_b = [line for line in lines if line.startswith("2026-10-20-lane-b ")]
    assert (
        len(line_a) == 1 and "stale=true" in line_a[0] and "state=active" in line_a[0]
    )
    assert len(line_b) == 1 and "stale=false" in line_b[0]
    assert "HALT" not in lines
    data = json.loads(_ok(_run(lane_repo.main, "list", "--json")))
    assert isinstance(data, list)
    by_lane = {entry["lane"]: entry for entry in data}
    assert by_lane["2026-10-20-lane-a"]["stale"] is True
    assert by_lane["2026-10-20-lane-b"]["stale"] is False
    (lane_repo.lanes_dir / "HALT").write_text("stop\n", encoding="utf-8")
    assert "HALT" in _ok(_run(lane_repo.main, "list")).splitlines()
    proc = _run(lane_repo.main, "list", "--json")
    assert isinstance(json.loads(_ok(proc)), list)
    assert "HALT" in proc.stderr.splitlines()


def test_ac784_6_list_with_no_cards_is_empty(lane_repo: LaneRepo) -> None:
    assert json.loads(_ok(_run(lane_repo.main, "list", "--json"))) == []


def test_ac784_6_list_takes_no_lock(
    lane_repo: LaneRepo, holders: list[_Holder]
) -> None:
    _ok(_claim(lane_repo, lane_repo.wt1, "2026-10-20-lane-a", "s-one"))
    holders.append(_Holder(lane_repo.lanes_dir / "registry.lock"))
    start = time.monotonic()
    data = json.loads(_ok(_run(lane_repo.main, "list", "--json")))
    assert time.monotonic() - start < LIST_MAX_S
    assert [entry["lane"] for entry in data] == ["2026-10-20-lane-a"]


def test_ac784_6_the_ref_guard_inventory_is_not_a_card(lane_repo: LaneRepo) -> None:
    # The ref guard writes its install inventory beside the cards (AC-784.15).
    _write(
        lane_repo.lanes_dir / "ref-guard.json",
        json.dumps({"schema": "ref-guard/1"}) + "\n",
    )
    _ok(_claim(lane_repo, lane_repo.wt1, "2026-10-20-lane-a", "s-one"))
    data = json.loads(_ok(_run(lane_repo.main, "list", "--json")))
    assert [entry["lane"] for entry in data] == ["2026-10-20-lane-a"]
    assert "ref-guard" not in _ok(_run(lane_repo.main, "list"))
    # No lane can take the inventory's name.
    _refused(
        _run(
            lane_repo.main, "beat", "--plan", f"{PLANS}/ref-guard", "--session", "s-one"
        ),
        "plan_bad",
    )
    assert _lanes().GUARD_INVENTORY == "ref-guard.json"


# ---------------------------------------------------------------------------
# AC-784.7: ownership entries and the component-aware rule
# ---------------------------------------------------------------------------


def _ownership_file(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "plan" / "task.md"
    _write(path, text)
    return path


def test_ac784_7_load_ownership_reads_the_section(tmp_path: Path) -> None:
    lanes = _lanes()
    path = _ownership_file(
        tmp_path,
        _task_text((["tools/lanes.py", "tests/tooling/"], [".agent/context/"])),
    )
    assert lanes._load_ownership(path) == (
        ["tools/lanes.py", "tests/tooling/"],
        [".agent/context/"],
    )
    path = _ownership_file(tmp_path, _task_text((["tools/"], [])))
    assert lanes._load_ownership(path) == (["tools/"], [])


def test_ac784_7_load_ownership_refuses_a_bad_section(tmp_path: Path) -> None:
    lanes = _lanes()
    head = "# Task\n\n## Lane Ownership\n\n```yaml\n"
    cases = [
        ("no_ownership", _task_text(None)),
        (
            "ownership_bad:gates",
            head + "owns:\n  - a/\nmust_not_touch: []\ngates: []\n```\n",
        ),
        ("ownership_bad:must_not_touch", head + "owns:\n  - a/\n```\n"),
        ("ownership_bad:owns", head + "owns: a/\nmust_not_touch: []\n```\n"),
    ]
    for reason, text in cases:
        with pytest.raises(lanes.Refusal) as caught:
            lanes._load_ownership(_ownership_file(tmp_path, text))
        assert caught.value.reason == reason, (reason, caught.value.reason)


def test_ac784_7_each_refused_entry_shape(tmp_path: Path) -> None:
    lanes = _lanes()
    bad = [
        "/abs/path",
        "C:/x",
        "c:x",
        "a\\b",
        "../a",
        "a/../b",
        "./a",
        "a/./b",
        ".",
        "..",
        "a//b",
        "a/*",
        "a?b",
        "a[1]",
        "*",
    ]
    for entry in bad:
        text = _task_text(([entry], []))
        with pytest.raises(lanes.Refusal) as caught:
            lanes._load_ownership(_ownership_file(tmp_path, text))
        assert caught.value.reason == f"entry_bad:{entry}", (entry, caught.value.reason)
        text = _task_text((["ok/"], [entry]))
        with pytest.raises(lanes.Refusal) as caught:
            lanes._load_ownership(_ownership_file(tmp_path, text))
        assert caught.value.reason == f"entry_bad:{entry}", (entry, caught.value.reason)
    text = "# Task\n\n## Lane Ownership\n\n```yaml\nowns:\n  - ''\nmust_not_touch: []\n```\n"
    with pytest.raises(lanes.Refusal) as caught:
        lanes._load_ownership(_ownership_file(tmp_path, text))
    assert caught.value.reason == "entry_bad:"


def test_ac784_7_contradictory_ownership_is_refused(tmp_path: Path) -> None:
    lanes = _lanes()
    for owns, mnt in (
        (["a/"], ["a/b.py"]),
        (["a/b.py"], ["a/"]),
        (["a/b.py"], ["a/b.py"]),
        (["a/b"], ["a/b/"]),
    ):
        with pytest.raises(lanes.Refusal) as caught:
            lanes._load_ownership(_ownership_file(tmp_path, _task_text((owns, mnt))))
        assert caught.value.reason.startswith("ownership_contradiction"), (
            owns,
            mnt,
            caught.value.reason,
        )
    # Component-aware: a/b does not hold a/bc.
    assert lanes._load_ownership(
        _ownership_file(tmp_path, _task_text((["a/b"], ["a/bc"])))
    ) == (["a/b"], ["a/bc"])
    assert lanes._load_ownership(
        _ownership_file(tmp_path, _task_text((["a/b/"], ["a/bc"])))
    ) == (["a/b/"], ["a/bc"])


def test_ac784_7_overlap_is_component_aware() -> None:
    lanes = _lanes()
    assert lanes._overlaps("a/", "a/b.py")
    assert lanes._overlaps("a/b.py", "a/")
    assert lanes._overlaps("a/", "a/")
    assert lanes._overlaps("a/b.py", "a/b.py")
    assert lanes._overlaps("a/b", "a/b/")
    assert lanes._overlaps("a/", "a/b/c/d.py")
    assert not lanes._overlaps("a/b", "a/bc")
    assert not lanes._overlaps("a/b/", "a/bc")
    assert not lanes._overlaps("a/b.py", "a/b.pyc")
    assert not lanes._overlaps("a/", "ab/c.py")


def test_ac784_7_normalization_is_nfc_then_case_fold() -> None:
    lanes = _lanes()
    decomposed = unicodedata.normalize("NFD", "docs/café.md")
    composed = unicodedata.normalize("NFC", "docs/café.md")
    assert decomposed != composed
    assert lanes._normalize(decomposed, ignorecase=False) == composed
    assert lanes._normalize("Tools/Lanes.py", ignorecase=True) == "tools/lanes.py"
    assert lanes._normalize("Tools/Lanes.py", ignorecase=False) == "Tools/Lanes.py"


def test_ac784_7_claim_refuses_a_contradiction(lane_repo: LaneRepo) -> None:
    _refused(
        _claim(lane_repo, lane_repo.wt1, "2026-10-20-lane-contra", "s-one"),
        "ownership_contradiction",
    )
    assert not lane_repo.card_path("2026-10-20-lane-contra").exists()


# ---------------------------------------------------------------------------
# AC-784.8: check
# ---------------------------------------------------------------------------


def _plan_in(wt: Path, slug: str, owns: list[str], mnt: list[str]) -> str:
    """Commit a plan in ``wt`` (detached HEAD) so it is not part of the change set."""
    rel = f"{PLANS}/{slug}"
    _write(wt / rel / "task.md", _task_text((owns, mnt)))
    _git(wt, "add", "-A")
    _git(wt, "commit", "-q", "-m", f"plan {slug}")
    return rel


def _check(wt: Path, plan: str, *extra: str) -> subprocess.CompletedProcess[str]:
    return _run(wt, "check", "--plan", plan, *extra)


def test_ac784_8_clean_and_owned_changes_pass(lane_repo: LaneRepo) -> None:
    wt = lane_repo.wt1
    plan = f"{PLANS}/2026-10-20-lane-a"
    assert "check_ok" in _ok(_check(wt, plan)).splitlines()
    _write(wt / "src/a.py", "A = 2\n")
    _write(wt / "src/new_tool.py", "N = 1\n")
    assert "check_ok" in _ok(_check(wt, plan)).splitlines()


def test_ac784_8_change_outside_owns_exits_1(lane_repo: LaneRepo) -> None:
    wt = lane_repo.wt1
    _write(wt / "other/o.py", "O = 2\n")
    _write(wt / "brand/new.py", "X = 1\n")
    proc = _check(wt, f"{PLANS}/2026-10-20-lane-a")
    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    lines = proc.stdout.splitlines()
    assert "outside_owns:other/o.py" in lines
    assert "outside_owns:brand/new.py" in lines


def test_ac784_8_must_not_touch_is_reported(lane_repo: LaneRepo) -> None:
    wt = lane_repo.wt1
    _write(wt / "docs/x.md", "# changed\n")
    proc = _check(wt, f"{PLANS}/2026-10-20-lane-a")
    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    assert "must_not_touch:docs/x.md" in proc.stdout.splitlines()


def test_ac784_8_rename_counts_both_paths(lane_repo: LaneRepo) -> None:
    wt = lane_repo.wt1
    _git(wt, "mv", "src/a.py", "other/a.py")
    proc = _check(wt, f"{PLANS}/2026-10-20-lane-a")
    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    assert "outside_owns:other/a.py" in proc.stdout.splitlines()
    assert "src/a.py" in proc.stdout
    # The reverse rename: the old path is outside owns.
    wt2 = lane_repo.wt2
    _git(wt2, "mv", "other/o.py", "src/o.py")
    proc = _check(wt2, f"{PLANS}/2026-10-20-lane-a")
    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    assert "outside_owns:other/o.py" in proc.stdout.splitlines()
    assert "src/o.py" in proc.stdout


def test_ac784_8_deletion_outside_owns_is_reported(lane_repo: LaneRepo) -> None:
    wt = lane_repo.wt1
    (wt / "other/o.py").unlink()
    proc = _check(wt, f"{PLANS}/2026-10-20-lane-a")
    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    assert "outside_owns:other/o.py" in proc.stdout.splitlines()


def test_ac784_8_new_file_named_exactly_in_owns_is_owned(lane_repo: LaneRepo) -> None:
    wt = lane_repo.wt1
    _write(wt / "docs/new.md", "# new\n")
    assert "check_ok" in _ok(_check(wt, f"{PLANS}/2026-10-20-lane-b")).splitlines()
    _write(wt / "docs/newer.md", "# newer\n")
    proc = _check(wt, f"{PLANS}/2026-10-20-lane-b")
    assert proc.returncode == 1
    assert "outside_owns:docs/newer.md" in proc.stdout.splitlines()


def test_ac784_8_base_includes_committed_changes(lane_repo: LaneRepo) -> None:
    wt = lane_repo.wt1
    plan = _plan_in(
        wt, "2026-10-21-lane-base", ["tools/", f"{PLANS}/2026-10-21-lane-base/"], []
    )
    _write(wt / "other/o.py", "O = 3\n")
    _git(wt, "commit", "-q", "-am", "outside change")
    # Against HEAD nothing is uncommitted; against the fixture base the commit counts.
    assert "check_ok" in _ok(_check(wt, plan)).splitlines()
    proc = _check(wt, plan, "--base", lane_repo.base)
    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    assert "outside_owns:other/o.py" in proc.stdout.splitlines()


def test_ac784_8_case_folding_follows_core_ignorecase(lane_repo: LaneRepo) -> None:
    wt = lane_repo.wt1
    plan = _plan_in(wt, "2026-10-21-lane-case", ["TOOLS/"], [])
    _write(wt / "tools/a.py", "A = 5\n")
    _git(lane_repo.main, "config", "core.ignorecase", "true")
    assert "check_ok" in _ok(_check(wt, plan)).splitlines()
    _git(lane_repo.main, "config", "core.ignorecase", "false")
    proc = _check(wt, plan)
    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    assert "outside_owns:tools/a.py" in proc.stdout.splitlines()


def test_ac784_8_paths_compare_after_nfc(lane_repo: LaneRepo) -> None:
    wt = lane_repo.wt1
    plan = _plan_in(
        wt, "2026-10-21-lane-nfc", [unicodedata.normalize("NFD", "docs/café.md")], []
    )
    _write(wt / unicodedata.normalize("NFC", "docs/café.md"), "# cafe\n")
    assert "check_ok" in _ok(_check(wt, plan)).splitlines()


def test_ac784_8_an_entry_through_a_link_is_refused(
    lane_repo: LaneRepo, tmp_path: Path
) -> None:
    wt = lane_repo.wt1
    plan = _plan_in(wt, "2026-10-21-lane-link", ["linkdir/"], [])
    _make_dir_link(wt / "linkdir", tmp_path / "outside-target")
    proc = _check(wt, plan)
    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    assert "link_path:linkdir/" in proc.stdout.splitlines()


def test_ac784_8_through_link_uses_filesystem_metadata(tmp_path: Path) -> None:
    lanes = _lanes()
    root = tmp_path / "tree"
    (root / "tools").mkdir(parents=True)
    (root / "tools" / "a.py").write_text("A = 1\n", encoding="utf-8")
    _make_dir_link(root / "linkdir", tmp_path / "elsewhere")
    assert lanes._through_link(root, "linkdir/x.py") is True
    assert lanes._through_link(root, "linkdir/") is True
    assert lanes._through_link(root, "tools/a.py") is False
    assert lanes._through_link(root, "tools/") is False
    # A path that does not exist yet (a new file) is not a link.
    assert lanes._through_link(root, "missing/new.py") is False


# ---------------------------------------------------------------------------
# AC-784.9: registry_busy
# ---------------------------------------------------------------------------


def test_ac784_9_registry_busy_names_the_holder(
    lane_repo: LaneRepo,
    holders: list[_Holder],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lanes = _lanes()
    holder = _Holder(lane_repo.lanes_dir / "registry.lock")
    holders.append(holder)
    monkeypatch.chdir(lane_repo.wt1)
    start = time.monotonic()
    code = lanes.main(
        [
            "claim",
            "--plan",
            f"{PLANS}/2026-10-20-lane-a",
            "--worktree",
            str(lane_repo.wt1),
            "--session",
            "s-one",
        ],
        wait_s=WAIT_S,
        poll_s=POLL_S,
    )
    elapsed = time.monotonic() - start
    out = capsys.readouterr().out
    assert code == 1, out
    assert any(
        line.startswith("refused: registry_busy") for line in out.splitlines()
    ), out
    assert str(holder.pid) in out
    assert "holder.py" in out
    assert "does not mean the holder died" in out
    assert WAIT_S <= elapsed < 60
    assert not lane_repo.card_path("2026-10-20-lane-a").exists()


# ---------------------------------------------------------------------------
# AC-784.10: templates and workflow text; claim needs the section
# ---------------------------------------------------------------------------


def _template(name: str) -> Path:
    """A package template: ``.agent/templates/`` in an adopter, ``templates/`` in the package."""
    adopted = ROOT / ".agent/templates" / name
    return adopted if adopted.is_file() else ROOT / "templates" / name


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    rest = text[start + len(heading) :]
    nxt = re.search(r"^## ", rest, flags=re.MULTILINE)
    return rest if nxt is None else rest[: nxt.start()]


def _paragraphs(text: str) -> list[str]:
    return [p for p in re.split(r"\n\s*\n", text) if p.strip()]


def test_ac784_10_claim_without_the_ownership_section_is_refused(
    lane_repo: LaneRepo,
) -> None:
    _refused(
        _claim(lane_repo, lane_repo.wt1, "2026-10-20-lane-none", "s-one"),
        "no_ownership",
    )
    assert not lane_repo.card_path("2026-10-20-lane-none").exists()


def test_ac784_10_task_template_has_an_optional_lane_ownership_section(
    tmp_path: Path,
) -> None:
    lanes = _lanes()
    text = _template("TASK-TEMPLATE.md").read_text(encoding="utf-8")
    assert "## Lane Ownership" in text
    section = _section(text, "## Lane Ownership")
    assert "optional" in section.lower()
    assert "```yaml" in section and "owns:" in section and "must_not_touch:" in section
    # The template's own example parses under the claim's reader.
    owns, mnt = lanes._load_ownership(_ownership_file(tmp_path, text))
    assert isinstance(owns, list) and isinstance(mnt, list)


def test_ac784_10_handoff_template_has_integration_requests() -> None:
    text = _template("HANDOFF-TEMPLATE.md").read_text(encoding="utf-8")
    assert "Integration requests" in text
    assert "<lane>/<generation>/<n>" in text
    lowered = text.lower()
    assert "facts and intent" in lowered
    assert "snapshot" in lowered


def test_ac784_10_execution_session_workflow_beats_at_every_row_boundary() -> None:
    text = (ROOT / ".agent/workflows/execution-session.md").read_text(encoding="utf-8")
    paragraphs = _paragraphs(text)
    beat = [p for p in paragraphs if "lanes.py beat" in p]
    assert beat, "execution-session.md names no `lanes.py beat` step"
    assert any(
        "row" in p
        and "HALT" in p
        and "exit 3" in p
        and "card_superseded" in p
        and "human" in p
        for p in beat
    ), beat
    assert any(
        "lanes.py claim" in p and "Lane Ownership" in p and "only" in p
        for p in paragraphs
    )
    assert "lanes.py release" in text
    assert "lanes.py list" in text


def _documented_lane_commands(text: str) -> dict[str, str]:
    """The workflow's claim, beat and release commands: the words after ``lanes.py``."""
    found: dict[str, str] = {}
    for span in re.findall(
        r"`[^`]*tools/lanes\.py ((?:claim|beat|release)[^`]*)`", text
    ):
        found.setdefault(span.split()[0], span)
    return found


def test_ac784_10_the_documented_lane_commands_run_without_a_session_variable(
    lane_repo: LaneRepo,
) -> None:
    # R1-F4: the claim, beat and release that execution-session.md prescribes, run as
    # written with no session variable set, carry their own session.
    assert _lanes().SESSION_ENV not in os.environ
    text = (ROOT / ".agent/workflows/execution-session.md").read_text(encoding="utf-8")
    commands = _documented_lane_commands(text)
    assert set(commands) == {"claim", "beat", "release"}, commands
    values = {
        "<plan dir>": f"{PLANS}/2026-10-20-lane-a",
        "<path>": lane_repo.wt1.as_posix(),
        "<session id>": "s-doc",
    }

    def argv(verb: str) -> list[str]:
        words = commands[verb]
        for key, value in values.items():
            words = words.replace(key, value)
        assert "<" not in words, words
        return shlex.split(words)

    _ok(_run(lane_repo.wt1, *argv("claim")))
    assert lane_repo.card("2026-10-20-lane-a")["session"] == "s-doc"
    _ok(_run(lane_repo.wt1, *argv("beat")))
    # The workflow releases after the lane worktree is removed, from the main tree.
    _git(lane_repo.main, "worktree", "remove", str(lane_repo.wt1))
    _ok(_run(lane_repo.main, *argv("release")))
    assert lane_repo.card("2026-10-20-lane-a")["state"] == "released"


def test_ac784_10_create_plan_workflow_reads_the_lanes_at_session_start() -> None:
    text = (ROOT / ".agent/workflows/create-plan.md").read_text(encoding="utf-8")
    for token in (
        "lanes.py list",
        "HALT",
        "lanes.py claim",
        "lanes.py beat",
        "Lane Ownership",
    ):
        assert token in text, token
