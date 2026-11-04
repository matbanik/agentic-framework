"""Lane-route tooling: the policy reader, create/land/commit/remove and the secrets scan.

Every
new name is reached through its module (``executor_worktree._lane_route``,
``lanes.SCAN_ENTRY_ENV``), never through ``from ... import``, so the file collects on
the unchanged tree.

Design choices (the tests pin each one):

* ``executor_worktree._lane_route(root: Path) -> Mapping[str, object]`` reads
  ``root/.agent/lane-route.json`` (``LANE_ROUTE_FILE``) of the MAIN tree. The result
  has ``required`` (bool) and ``exempt`` (a list or tuple of slugs). A missing file is
  ``required`` False with no ``exempt`` slug. A bad file raises
  ``executor_worktree._Refusal`` whose ``lines`` are ``["lane_route_bad:<reason>"]``,
  with ``<reason>`` one of: ``json`` (not a JSON object), ``schema`` (not
  ``lane-route/1``), ``required`` (not a JSON bool: ``1`` and ``"true"`` are refused),
  ``exempt`` (not a list), ``exempt_slug`` (an entry that does not match
  ``WORKTREE_SLUG_RE``), ``exempt_repeated`` and ``extra_key:<key>``. ``create``
  prints the same line and exits 1 before anything is made.
* ``create <slug> --lane-plan <dir> [--session <id>]``. ``--plan`` stays the
  run-identity slug. With ``--lane-plan`` the child
  ``tools/lanes.py claim --plan <dir> --worktree <path> [--session <id>]`` runs from
  the main tree after ``_populate``. Success prints the claim line
  ``claimed <lane> generation=<16 hex>``, then ``worktree_ready:<posix>`` as the last
  line. A refusal prints ``worktree_bad:claim:<reason>`` (the text after
  ``refused: ``), tears down the worktree and the branch, and exits 1.
* Under ``required: true`` a non-exempt slug without ``--lane-plan`` is
  ``worktree_bad:no_plan`` (the only stdout line, exit 1, nothing made).
* ``land`` under ``required: true`` on a non-exempt lane worktree: the first stdout
  line is ``land_fail:lane_route:<slug>``, exit 1, and stdout or stderr names
  ``tools/lanes.py land prepare``. The main tree status is byte-equal.
* ``commit_batch.py`` (CLI entry only) under ``required: true`` in a non-exempt lane
  worktree: the stdout JSON reason is ``lane_worktree``, stderr holds the
  ``commit_refused`` log, and stdout or stderr names ``tools/lanes.py commit``. The
  check runs right after ``_open_repo``.
* ``remove`` accepts the lane route through the read-only query
  ``tools/lanes.py landed --worktree <path>`` (run from the main tree), whose stdout
  line is ``landed:<L0>:<C>`` (C = the published main commit) or
  ``not_landed:<reason>``. A lane commit after L0 is ``not_landed:``.
* ``land prepare`` secrets scan (``lanes._scan_secrets``): the scanner argv is the
  module-level list ``lanes.SCAN_ENTRY`` (the pre-commit hook entry), which the environment
  variable named by ``lanes.SCAN_ENTRY_ENV`` (``{{PROJECT_NAME_UPPER}}_LANES_SCAN_ENTRY``) replaces
  with a JSON list of strings; the module docstring names that variable. Each
  element equal to ``{paths}`` is replaced by the scanned paths: every path that T
  changes against P, deletions skipped, repo-relative POSIX. The child runs with cwd
  = a scratch detached worktree at T whose ``.secrets.baseline`` holds P's bytes,
  and that worktree is removed after the scan. The scanner behaves as the v1.5.0
  hook under ``pre-commit run`` does (exit 1 for both cases): a new secret
  is reported as ``Location:    <path>:<line>`` with the baseline untouched; a line
  move rewrites only the ``line_number`` values. The stdout line of
  ``land prepare`` is exactly one of ``secrets_ok``, ``secrets_skip:no_baseline``
  or ``secrets_lines_moved:<n>``, and the same string is the one ``secrets_*``
  value in the land op journal. A refusal is ``refused: land_fail:secrets:<path>``
  or ``refused: land_fail:secrets:baseline_unreadable`` (exit 1, no
  ``land_ready``). The integrator still never stages a baseline.
* A ``meu-status`` request makes T carry the rendered BUILD_PLAN
  (``meu_status.py render --check`` passes in T). The plan's ``-> done`` example is
  not a valid status (``MEU_STATUSES``; the frozen ``_case_status_done`` refuses
  it), so the test uses a valid status change.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from tools.tests.run_parameters_fixtures import build_fixture as bf
from tools.tests.run_parameters_fixtures import phase_b3 as b3
from tools.tests import lane_worktree_config as lwc
from tools.tests import test_executor_worktree_lane as ewl
from tools.tests import test_lanes_integrate as integ
from tools.tests import test_lanes_recovery as rec

ROOT = Path(__file__).resolve().parents[2]
COMMIT_BATCH = ROOT / "tools" / "commit_batch.py"
LANE_ROUTE = ".agent/lane-route.json"
SCHEMA = "lane-route/1"
SESSION_ENV = "{{PROJECT_NAME_UPPER}}_SESSION"
SCAN_ENV = "{{PROJECT_NAME_UPPER}}_LANES_SCAN_ENTRY"
BASELINE = ".secrets.baseline"
PRE_COMMIT_CONFIG = ".pre-commit-config.yaml"
BUILD_PLAN = "docs/BUILD_PLAN.md"
LANE_NAME = "2026-11-02-lane-a"
LANE_PLAN = f"docs/execution/plans/{LANE_NAME}"
SESSION = "s-lane-route"
SLOW_S = 600
CHILD_TIMEOUT_S = 240
GENERATION_RE = re.compile(rf"claimed {LANE_NAME} generation=([0-9a-f]{{16}})")

EMPTY_BASELINE: dict[str, Any] = {
    "version": "1.5.0",
    "plugins_used": [],
    "filters_used": [],
    "results": {},
    "generated_at": "2026-11-02T00:00:00Z",
}

# A deterministic stand-in for the detect-secrets v1.5.0 hook under ``pre-commit run``.
# It finds ``PLANTED = "<value>"`` lines (hash: sha1 of the value), keeps the baseline
# untouched and names ``Location: <path>:<line>`` for a new one, rewrites only the line
# numbers for a moved one, and exits 1 in both cases (secret_exit=1,
# move_exit=1). Each call appends cwd, HEAD, paths and the baseline sha256 to the log.
FAKE_SCANNER = r'''
"""Fake detect-secrets hook of tests/tooling/test_lane_route_tooling.py."""
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

LOG = Path(__LOG__)
PATTERN = re.compile(r'PLANTED = "([^"]+)"')


def main() -> int:
    paths = sys.argv[1:]
    baseline = Path(".secrets.baseline")
    raw = baseline.read_bytes()
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    with LOG.open("a", encoding="utf-8") as out:
        out.write(
            json.dumps(
                {
                    "cwd": os.getcwd(),
                    "head": head,
                    "paths": paths,
                    "baseline_sha256": hashlib.sha256(raw).hexdigest(),
                }
            )
            + "\n"
        )
    data = json.loads(raw.decode("utf-8"))
    results = data.setdefault("results", {})
    new = []
    moved = False
    for rel in paths:
        path = Path(rel)
        if not path.is_file():
            continue
        known = {item["hashed_secret"]: item for item in results.get(rel, [])}
        text = path.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), 1):
            match = PATTERN.search(line)
            if match is None:
                continue
            digest = hashlib.sha1(match.group(1).encode("utf-8")).hexdigest()
            item = known.get(digest)
            if item is None:
                new.append((rel, number))
            elif item["line_number"] != number:
                item["line_number"] = number
                moved = True
    if new:
        print("ERROR: Potential secrets about to be committed to git repo!")
        for rel, number in new:
            print()
            print("Secret Type: Planted Fixture")
            print(f"Location:    {rel}:{number}")
        return 1
    if moved:
        baseline.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print("The baseline file was updated.")
        print("Probably to keep line numbers of secrets up-to-date.")
        return 1
    return 0


sys.exit(main())
'''


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _executor() -> ModuleType:
    return importlib.import_module("tools.executor_worktree")


def _lanes_module() -> ModuleType:
    return importlib.import_module("tools.lanes")


def _policy_bytes(required: object, exempt: object) -> bytes:
    return json.dumps(
        {"schema": SCHEMA, "required": required, "exempt": exempt}, indent=2
    ).encode("utf-8")


def _write_policy(root: Path, data: bytes) -> None:
    target = root / LANE_ROUTE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def _no_venv(path: Path) -> int:
    """``_build_venv`` stand-in that builds nothing (a lane with no ``.venv``)."""
    del path
    return 0


def _stripped(proc: subprocess.CompletedProcess[str]) -> list[str]:
    """The stdout lines with a ``refused: `` prefix removed."""
    return [line.removeprefix("refused: ").strip() for line in proc.stdout.splitlines()]


def _secrets_lines(proc: subprocess.CompletedProcess[str]) -> list[str]:
    return [line for line in proc.stdout.splitlines() if line.startswith("secrets_")]


def _walk_strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():  # pyright: ignore[reportUnknownVariableType] - JSON
            yield from _walk_strings(item)  # pyright: ignore[reportUnknownArgumentType]
    elif isinstance(value, list):
        for item in value:  # pyright: ignore[reportUnknownVariableType] - JSON
            yield from _walk_strings(item)  # pyright: ignore[reportUnknownArgumentType]


def _journal_secrets(lr: rec.LaneRig) -> list[str]:
    """Every ``secrets_*`` string of the land op record (``op.json``)."""
    record = json.loads(rec.op_file(lr).read_text(encoding="utf-8"))
    return [text for text in _walk_strings(record) if text.startswith("secrets_")]


@dataclass
class Scanner:
    """The fake scanner script, its JSON-lines call log and its argv entry."""

    script: Path
    log: Path

    @property
    def entry(self) -> list[str]:
        return [sys.executable, str(self.script), "{paths}"]

    @property
    def env(self) -> dict[str, str]:
        return {SCAN_ENV: json.dumps(self.entry)}

    def calls(self) -> list[dict[str, Any]]:
        if not self.log.is_file():
            return []
        lines = self.log.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()]


def _scanner(tmp_path: Path) -> Scanner:
    folder = tmp_path / "scanner"
    folder.mkdir(parents=True, exist_ok=True)
    log = folder / "calls.jsonl"
    script = folder / "fake_hook.py"
    script.write_text(
        FAKE_SCANNER.replace("__LOG__", repr(str(log))), encoding="utf-8", newline="\n"
    )
    return Scanner(script=script, log=log)


# ---------------------------------------------------------------------------
# Executor rig: one source repository and the in-process tool
# ---------------------------------------------------------------------------


@dataclass
class ExecRig:
    """``ewl._build_source`` and ``executor_worktree.main`` with captured output."""

    tool: ModuleType
    src: Path
    tmp: Path
    capfd: pytest.CaptureFixture[str]

    def call(self, *argv: object) -> tuple[int, list[str], str]:
        """``main(["--root", src, *argv])``; (exit code, stdout lines, stderr)."""
        self.capfd.readouterr()
        try:
            code = int(self.tool.main(["--root", str(self.src), *map(str, argv)]))
        except SystemExit as stop:
            code = stop.code if isinstance(stop.code, int) else 2
        captured = self.capfd.readouterr()
        return code, captured.out.splitlines(), captured.err

    def path(self, slug: str) -> Path:
        return Path(self.tool.WORKTREE_PARENT) / slug

    def policy(self, required: bool, exempt: list[str]) -> None:
        _write_policy(self.src, _policy_bytes(required, exempt))

    def create(self, slug: str, *extra: str) -> Path:
        code, lines, err = self.call("create", slug, *extra)
        wt = self.path(slug)
        assert code == 0 and lines[-1:] == [f"worktree_ready:{wt.as_posix()}"], (
            slug,
            code,
            lines,
            err,
        )
        return wt

    def status(self) -> bytes:
        proc = ewl._git_proc(  # pyright: ignore[reportPrivateUsage]
            self.src, "status", "--porcelain=v1", "-z", "--untracked-files=all"
        )
        assert proc.returncode == 0, proc.stderr
        return proc.stdout

    def card_path(self, lane: str) -> Path:
        return self.src / ".git" / "lanes" / f"{lane}.json"

    def lane_plan(self, owns: list[str] | None) -> None:
        """Write the lane plan's ``task.md`` in the main tree; ``None``: no ownership."""
        body = "# Lane A\n\n| 1 | row | `[ ]` |\n"
        if owns is not None:
            body += rec.ownership(owns)
        target = self.src / LANE_PLAN / "task.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8", newline="\n")

    def assert_nothing_left(self, slug: str, heads: dict[str, str]) -> None:
        wt = self.path(slug)
        assert not wt.exists(), f"{slug}: the refused create left {wt}"
        assert not ewl._listed(self.src, wt), f"{slug}: a worktree is left"  # pyright: ignore[reportPrivateUsage]
        assert ewl._ref(self.src, f"{ewl.REF_PREFIX}{slug}") is None, slug  # pyright: ignore[reportPrivateUsage]
        assert ewl._heads(self.src) == heads, f"{slug}: a branch changed"  # pyright: ignore[reportPrivateUsage]
        assert not self.card_path(LANE_NAME).exists(), "a lane card is left"


@pytest.fixture
def exec_rig(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> ExecRig:
    tool = _executor()
    monkeypatch.setattr(tool, "WORKTREE_PARENT", tmp_path / "wt", raising=False)
    monkeypatch.delenv("CREDITS_BASE_COMMIT", raising=False)

    def fake_venv(path: Path) -> int:
        ewl._write(Path(path), {".venv/pyvenv.cfg": b"home = stub\n"})  # pyright: ignore[reportPrivateUsage]
        return 0

    monkeypatch.setattr(tool, "_build_venv", fake_venv)
    src = ewl._build_source(tmp_path)  # pyright: ignore[reportPrivateUsage]
    # The packaged rig lists no junction files; ``claim`` reads them from this config, so the
    # lane-route cases need the fixture project's list. Commit it so the tree stays clean.
    config = json.loads(ewl.CONFIG_BYTES)
    config["junction_files"] = list(lwc.FIXTURE_JUNCTION_FILES)
    ewl._write(  # pyright: ignore[reportPrivateUsage]
        src, {ewl.CONFIG: (json.dumps(config) + chr(10)).encode("utf-8")}
    )
    ewl._git(src, "add", ewl.CONFIG)  # pyright: ignore[reportPrivateUsage]
    ewl._git(  # pyright: ignore[reportPrivateUsage]
        src, "commit", "-q", "--no-verify", "-m", "rig: junction files"
    )
    return ExecRig(tool=tool, src=src, tmp=tmp_path, capfd=capfd)


def _commit_batch(
    tmp_path: Path, repo: Path
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    """``commit_batch.py --repo <repo> --step candidate`` as a child; (proc, JSON)."""
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    env["CLAUDE_CONFIG_DIR"] = str(tmp_path / "claude-config")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(ROOT)
    proc = subprocess.run(
        [sys.executable, str(COMMIT_BATCH), "--repo", str(repo), "--step", "candidate"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=CHILD_TIMEOUT_S,
        check=False,
    )
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    assert lines, ("commit_batch printed no JSON", proc.returncode, proc.stderr)
    out = json.loads(lines[-1])
    assert isinstance(out, dict), out
    return proc, out


# ---------------------------------------------------------------------------
# _lane_route reads and validates the policy file
# ---------------------------------------------------------------------------


def _route_view(policy: Any) -> tuple[bool, list[str]]:
    return policy["required"], list(policy["exempt"])


def test_lane_route_returns_the_policy_of_a_valid_file(tmp_path: Path) -> None:
    _write_policy(tmp_path, _policy_bytes(True, ["mal-s2b", "lane-x"]))
    policy = _executor()._lane_route(tmp_path)
    assert _route_view(policy) == (True, ["mal-s2b", "lane-x"])
    _write_policy(tmp_path, _policy_bytes(False, []))
    assert _route_view(_executor()._lane_route(tmp_path)) == (False, [])


def test_lane_route_without_the_file_is_not_required(tmp_path: Path) -> None:
    assert not (tmp_path / LANE_ROUTE).exists()
    assert _route_view(_executor()._lane_route(tmp_path)) == (False, [])


BAD_SHAPES: list[tuple[str, bytes, str]] = [
    ("not_json", b"{not json\n", "json"),
    (
        "wrong_schema",
        json.dumps({"schema": "lane-route/2", "required": True, "exempt": []}).encode(),
        "schema",
    ),
    ("required_int", _policy_bytes(1, []), "required"),
    ("required_text", _policy_bytes("true", []), "required"),
    ("exempt_not_list", _policy_bytes(True, "mal-s2b"), "exempt"),
    ("exempt_bad_slug", _policy_bytes(True, ["Bad_Slug"]), "exempt_slug"),
    ("exempt_not_text", _policy_bytes(True, [7]), "exempt_slug"),
    ("exempt_repeated", _policy_bytes(True, ["lane-x", "lane-x"]), "exempt_repeated"),
    (
        "extra_key",
        json.dumps(
            {"schema": SCHEMA, "required": True, "exempt": [], "note": "x"}
        ).encode(),
        "extra_key:note",
    ),
]


@pytest.mark.parametrize(
    ("data", "reason"),
    [(data, reason) for _id, data, reason in BAD_SHAPES],
    ids=[case_id for case_id, _data, _reason in BAD_SHAPES],
)
def test_lane_route_refuses_a_bad_shape(
    tmp_path: Path, data: bytes, reason: str
) -> None:
    tool = _executor()
    _write_policy(tmp_path, data)
    with pytest.raises(tool._Refusal) as caught:
        tool._lane_route(tmp_path)
    assert caught.value.lines == [f"lane_route_bad:{reason}"]


def test_create_refuses_a_malformed_policy_and_makes_nothing(exec_rig: ExecRig) -> None:
    _write_policy(exec_rig.src, _policy_bytes(True, ["lane-x", "lane-x"]))
    heads = ewl._heads(exec_rig.src)  # pyright: ignore[reportPrivateUsage]
    code, lines, err = exec_rig.call("create", "lane-x")
    assert (code, lines) == (1, ["lane_route_bad:exempt_repeated"]), (lines, err)
    exec_rig.assert_nothing_left("lane-x", heads)


# ---------------------------------------------------------------------------
# create --lane-plan claims the lane, or tears down on a refusal
# ---------------------------------------------------------------------------


def test_create_with_a_lane_plan_claims_the_lane(exec_rig: ExecRig) -> None:
    exec_rig.lane_plan(["pkg/lane/"])
    code, lines, err = exec_rig.call(
        "create", "lane-a", "--lane-plan", LANE_PLAN, "--session", SESSION
    )
    wt = exec_rig.path("lane-a")
    assert code == 0, (code, lines, err)
    assert lines[-1:] == [f"worktree_ready:{wt.as_posix()}"], lines
    claimed = GENERATION_RE.fullmatch(lines[-2]) if len(lines) >= 2 else None
    assert claimed is not None, lines
    card = json.loads(exec_rig.card_path(LANE_NAME).read_text(encoding="utf-8"))
    assert os.path.samefile(card["worktree"], wt), card
    assert card["branch"] == "lane/lane-a", card
    assert card["generation"] == claimed.group(1), card
    assert card["plan"] == f"{LANE_PLAN}/", card
    assert card["session"] == SESSION, card


@pytest.mark.parametrize(
    ("owns", "line"),
    [
        (None, "worktree_bad:claim:no_ownership"),
        (
            ["pkg/lane/", BUILD_PLAN],
            f"worktree_bad:claim:owns_junction:{BUILD_PLAN}",
        ),
    ],
    ids=["no_ownership", "owns_junction"],
)
def test_create_with_a_refused_claim_tears_everything_down(
    exec_rig: ExecRig, owns: list[str] | None, line: str
) -> None:
    exec_rig.lane_plan(owns)
    heads = ewl._heads(exec_rig.src)  # pyright: ignore[reportPrivateUsage]
    code, lines, err = exec_rig.call(
        "create", "lane-a", "--lane-plan", LANE_PLAN, "--session", SESSION
    )
    assert code == 1, (code, lines, err)
    assert line in lines, (lines, err)
    assert not any(item.startswith("worktree_ready:") for item in lines), lines
    exec_rig.assert_nothing_left("lane-a", heads)


# ---------------------------------------------------------------------------
# create under required: true
# ---------------------------------------------------------------------------


def test_create_without_a_lane_plan_under_required_is_no_plan(
    exec_rig: ExecRig,
) -> None:
    exec_rig.policy(True, ["mal-s2b"])
    heads = ewl._heads(exec_rig.src)  # pyright: ignore[reportPrivateUsage]
    code, lines, err = exec_rig.call("create", "lane-b")
    assert (code, lines) == (1, ["worktree_bad:no_plan"]), (lines, err)
    exec_rig.assert_nothing_left("lane-b", heads)


def test_create_of_an_exempt_slug_under_required_is_unchanged(
    exec_rig: ExecRig,
) -> None:
    """Old behavior guard: an exempt slug needs no lane plan."""
    exec_rig.policy(True, ["lane-x"])
    exec_rig.create("lane-x")


@pytest.mark.parametrize("policy", ["absent", "not_required"])
def test_create_without_a_required_policy_is_unchanged(
    exec_rig: ExecRig, policy: str
) -> None:
    """Old behavior guard: no file, or ``required: false``, creates as before."""
    if policy == "not_required":
        exec_rig.policy(False, [])
    exec_rig.create("lane-n")


# ---------------------------------------------------------------------------
# land under required: true
# ---------------------------------------------------------------------------


def test_land_of_a_lane_worktree_under_required_is_refused(exec_rig: ExecRig) -> None:
    wt = exec_rig.create("lane-c")
    ewl._write(wt, {"pkg/new_work.py": b"NEW = 1\n"})  # pyright: ignore[reportPrivateUsage]
    exec_rig.policy(True, ["mal-s2b"])
    before = exec_rig.status()
    code, lines, err = exec_rig.call("land", wt)
    assert code == 1, (code, lines, err)
    assert lines[:1] == ["land_fail:lane_route:lane-c"], (lines, err)
    assert "tools/lanes.py land prepare" in "\n".join([*lines, err]), (lines, err)
    assert exec_rig.status() == before, "the refused land changed the main tree"
    assert not (exec_rig.src / "pkg/new_work.py").exists()


def test_land_of_an_exempt_worktree_under_required_is_unchanged(
    exec_rig: ExecRig,
) -> None:
    """Old behavior guard: an exempt slug lands with ``land_ok``."""
    exec_rig.policy(True, ["lane-e"])
    wt = exec_rig.create("lane-e")
    ewl._write(wt, {"pkg/new_work.py": b"NEW = 1\n"})  # pyright: ignore[reportPrivateUsage]
    code, lines, err = exec_rig.call("land", wt)
    assert (code, lines) == (0, ["land_ok:1:0:0"]), (lines, err)
    landed = (exec_rig.src / "pkg/new_work.py").read_bytes().replace(b"\r\n", b"\n")
    assert landed == b"NEW = 1\n"


# ---------------------------------------------------------------------------
# commit_batch.py under required: true
# ---------------------------------------------------------------------------


def test_commit_batch_in_a_lane_worktree_under_required_is_refused(
    exec_rig: ExecRig,
) -> None:
    wt = exec_rig.create("lane-d")
    exec_rig.policy(True, ["mal-s2b"])
    tip = ewl._ref(exec_rig.src, "refs/heads/lane/lane-d")  # pyright: ignore[reportPrivateUsage]
    main = ewl._ref(exec_rig.src, "refs/heads/main")  # pyright: ignore[reportPrivateUsage]
    proc, out = _commit_batch(exec_rig.tmp, wt)
    assert proc.returncode != 0, (proc.stdout, proc.stderr)
    assert out.get("result") == "refused", out
    assert out.get("reason") == "lane_worktree", (out, proc.stderr)
    assert "commit_refused" in proc.stderr, proc.stderr
    assert "tools/lanes.py commit" in proc.stdout + proc.stderr, proc.stderr
    assert ewl._ref(exec_rig.src, "refs/heads/lane/lane-d") == tip  # pyright: ignore[reportPrivateUsage]
    assert ewl._ref(exec_rig.src, "refs/heads/main") == main  # pyright: ignore[reportPrivateUsage]


def test_commit_batch_in_the_main_tree_is_not_lane_refused(exec_rig: ExecRig) -> None:
    """Old behavior guard: the main tree is never ``lane_worktree``."""
    exec_rig.policy(True, ["mal-s2b"])
    _proc, out = _commit_batch(exec_rig.tmp, exec_rig.src)
    assert out.get("reason") != "lane_worktree", out


def test_commit_batch_in_an_exempt_lane_worktree_is_not_lane_refused(
    exec_rig: ExecRig,
) -> None:
    """Old behavior guard: an exempt lane worktree is never ``lane_worktree``."""
    exec_rig.policy(True, ["lane-x"])
    wt = exec_rig.create("lane-x")
    _proc, out = _commit_batch(exec_rig.tmp, wt)
    assert out.get("reason") != "lane_worktree", out


# ---------------------------------------------------------------------------
# remove after the old route and after the lane route
# ---------------------------------------------------------------------------


def test_remove_after_an_old_route_land_is_unchanged(exec_rig: ExecRig) -> None:
    """Old behavior guard: land, then remove."""
    exec_rig.policy(True, ["lane-o"])
    wt = exec_rig.create("lane-o")
    ewl._write(wt, {"pkg/new_work.py": b"NEW = 1\n"})  # pyright: ignore[reportPrivateUsage]
    assert exec_rig.call("land", wt)[:2] == (0, ["land_ok:1:0:0"])
    code, lines, err = exec_rig.call("remove", wt)
    assert (code, lines) == (0, [f"worktree_removed:{wt.as_posix()}"]), (lines, err)
    assert not ewl._listed(exec_rig.src, wt)  # pyright: ignore[reportPrivateUsage]


def test_remove_after_an_old_route_land_and_an_edit_is_unlanded(
    exec_rig: ExecRig,
) -> None:
    """Guard: an edit after the old-route land fails both states."""
    exec_rig.policy(True, ["lane-o"])
    wt = exec_rig.create("lane-o")
    ewl._write(wt, {"pkg/new_work.py": b"NEW = 1\n"})  # pyright: ignore[reportPrivateUsage]
    assert exec_rig.call("land", wt)[:2] == (0, ["land_ok:1:0:0"])
    ewl._write(wt, {"pkg/new_work.py": b"NEW = 2\n"})  # pyright: ignore[reportPrivateUsage]
    code, lines, err = exec_rig.call("remove", wt)
    assert (code, lines) == (1, ["worktree_bad:unlanded"]), (lines, err)
    assert ewl._listed(exec_rig.src, wt) and wt.is_dir()  # pyright: ignore[reportPrivateUsage]


@dataclass
class RouteRig:
    """A ``phase_b3`` lane made by ``executor_worktree.py create``, claimed, committed."""

    lr: rec.LaneRig
    tool: ModuleType
    wt: Path
    capfd: pytest.CaptureFixture[str]

    def remove(self) -> tuple[int, list[str], str]:
        """In-process ``remove <wt>`` with the fixture environment."""
        rig = self.lr.rig
        with bf.patched_environ(rig.fx.env(**{SESSION_ENV: self.lr.session})):
            self.capfd.readouterr()
            code = int(
                self.tool.main(["--root", str(rig.repo), "remove", str(self.wt)])
            )
            captured = self.capfd.readouterr()
        return code, captured.out.splitlines(), captured.err

    def landed(self) -> subprocess.CompletedProcess[str]:
        """``tools/lanes.py landed --worktree <wt>`` from the main tree."""
        return rec.lanes(
            self.lr.repo,
            self.lr.rig.fx.env,
            "landed",
            "--worktree",
            str(self.wt),
            session=self.lr.session,
        )

    def commit(self, files: dict[str, bytes], message: str) -> str:
        for rel, data in files.items():
            target = self.wt / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        rec.git(self.wt, "add", "-A")
        rec.git(self.wt, "commit", "-q", "-m", message)
        return rec.git(self.wt, "rev-parse", "HEAD")


def _route_rig(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> RouteRig:
    """Setup only: create (old route, no policy), claim, one lane commit and handoff."""
    tool = _executor()
    monkeypatch.setattr(tool, "WORKTREE_PARENT", tmp_path / "wt", raising=False)
    monkeypatch.setattr(tool, "_build_venv", _no_venv)
    monkeypatch.delenv("CREDITS_BASE_COMMIT", raising=False)
    rig = b3.rig(tmp_path / "fx", ROOT, seed=lwc.SEED)
    rig.bind()
    rec.seed_plan(rig, rig.plan, {rec.METRICS: rec.METRICS_HEAD.encode()})
    p = rig.ref()
    plan = rig.plan
    session = rec.CARD_SESSION
    with bf.patched_environ(rig.fx.env(**{SESSION_ENV: session})):
        capfd.readouterr()
        code = int(tool.main(["--root", str(rig.repo), "create", plan]))
        created = capfd.readouterr()
    wt = Path(tool.WORKTREE_PARENT) / plan
    assert code == 0, (created.out, created.err)
    claim = rec.lanes(
        wt,
        rig.fx.env,
        "claim",
        "--plan",
        f"{rec.PLANS}/{plan}",
        "--worktree",
        str(wt),
        "--session",
        session,
        session=session,
    )
    assert claim.returncode == 0, (claim.stdout, claim.stderr)
    card = json.loads((rig.fx.common_dir / "lanes" / f"{plan}.json").read_text("utf-8"))
    generation = str(card["generation"])
    changed = f"src/{plan}/lane.py"
    handoff = rec.handoff_text(plan, []).replace("{gen}", f"{plan}/{generation}")
    route = RouteRig(
        lr=rec.LaneRig(
            rig=rig,
            plan=plan,
            session=session,
            wt=wt.resolve(),
            scratch=tmp_path / "scratch",
            message=tmp_path / "scratch" / "land-message.txt",
            p=p,
            l0="",
            changed=changed,
        ),
        tool=tool,
        wt=wt,
        capfd=capfd,
    )
    route.lr.scratch.mkdir(parents=True, exist_ok=True)
    route.lr.message.write_bytes(f"feat: land the {plan} lane\n".encode())
    route.lr.l0 = route.commit(
        {
            changed: f"LANE = {plan!r}\n".encode(),
            f"{rec.HANDOFFS}/{plan}-handoff.md": handoff.encode("utf-8"),
            f"{rec.HANDOFFS}/{plan}-implementation-critical-review.md": (
                b"# Review\n\nVerdict: approved\n"
            ),
        },
        f"lane: work of {plan}",
    )
    return route


def _published(route: RouteRig) -> str:
    """Prepare, approve and publish the lane; return C (main after the publish)."""
    rec.ready(route.lr)
    rec.ok(rec.publish(route.lr))
    return rec.main_ref(route.lr)


@pytest.mark.timeout(SLOW_S)
def test_remove_after_a_lane_route_publish_removes_the_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    route = _route_rig(tmp_path, monkeypatch, capfd)
    c = _published(route)
    query = route.landed()
    assert f"landed:{route.lr.l0}:{c}" in query.stdout.splitlines(), (
        query.returncode,
        query.stdout,
        query.stderr,
    )
    code, lines, err = route.remove()
    assert (code, lines) == (0, [f"worktree_removed:{route.wt.as_posix()}"]), (
        lines,
        err,
    )
    assert route.wt.resolve() not in rec.worktrees(route.lr)


@pytest.mark.timeout(SLOW_S)
def test_remove_after_a_lane_route_publish_and_an_edit_is_unlanded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    """Guard: an edit after the publish fails state (b) as well as state (a)."""
    route = _route_rig(tmp_path, monkeypatch, capfd)
    _published(route)
    (route.wt / route.lr.changed).write_bytes(b"EDITED = 1\n")
    code, lines, err = route.remove()
    assert (code, lines) == (1, ["worktree_bad:unlanded"]), (lines, err)
    assert route.wt.resolve() in rec.worktrees(route.lr)


@pytest.mark.timeout(SLOW_S)
def test_remove_after_a_lane_commit_past_l0_is_unlanded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    route = _route_rig(tmp_path, monkeypatch, capfd)
    _published(route)
    tip = route.commit({f"src/{route.lr.plan}/later.py": b"LATER = 1\n"}, "lane: later")
    query = route.landed()
    shown = query.stdout.splitlines()
    assert len(shown) == 1 and shown[0].startswith("not_landed:"), (
        query.returncode,
        query.stdout,
        query.stderr,
    )
    code, lines, err = route.remove()
    assert (code, lines) == (1, ["worktree_bad:unlanded"]), (lines, err)
    assert route.wt.resolve() in rec.worktrees(route.lr)
    assert rec.git(route.lr.repo, "rev-parse", route.lr.branch_ref) == tip


# ---------------------------------------------------------------------------
# the secrets scan of land prepare
# ---------------------------------------------------------------------------


def _baseline_bytes(results: dict[str, Any] | None = None) -> bytes:
    data = dict(EMPTY_BASELINE)
    data["results"] = results or {}
    return (json.dumps(data, indent=2) + "\n").encode("utf-8")


def _secrets_lane(tmp_path: Path, extra: dict[str, bytes]) -> rec.LaneRig:
    """Setup only: ``rec.lane_rig`` with ``extra`` files (a baseline) committed at P."""
    rig = b3.rig(tmp_path / "fx", ROOT, seed=lwc.SEED)
    rig.bind()
    files = {rec.METRICS: rec.METRICS_HEAD.encode(), **extra}
    rec.seed_plan(rig, rig.plan, files)
    return rec.open_lane(rig, tmp_path, rig.plan, rec.CARD_SESSION)


def _lane_commit(lr: rec.LaneRig, files: dict[str, bytes], message: str) -> None:
    """One more lane commit; L0 moves to it."""
    for rel, data in files.items():
        target = lr.wt / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    rec.git(lr.wt, "add", "-A")
    rec.git(lr.wt, "commit", "-q", "-m", message)
    lr.l0 = rec.git(lr.wt, "rev-parse", "HEAD")


def _blob(lr: rec.LaneRig, rev: str, rel: str) -> str:
    return rec.git(lr.repo, "rev-parse", f"{rev}:{rel}")


def _changed(lr: rec.LaneRig, p: str, t: str) -> set[str]:
    out = rec.git(lr.repo, "diff", "--name-only", "--diff-filter=d", p, t)
    return {line for line in out.splitlines() if line.strip()}


@pytest.mark.timeout(SLOW_S)
def test_land_prepare_records_secrets_ok_for_a_clean_lane(tmp_path: Path) -> None:
    baseline = _baseline_bytes()
    lr = _secrets_lane(tmp_path, {BASELINE: baseline})
    scanner = _scanner(tmp_path)
    p = rec.main_ref(lr)
    proc = rec.prepare(lr, env=scanner.env)
    rec.ok(proc)
    assert _secrets_lines(proc) == ["secrets_ok"], proc.stdout
    assert _journal_secrets(lr) == ["secrets_ok"]
    t = rec.kept_refs(lr)["T"]
    calls = scanner.calls()
    assert len(calls) == 1, calls
    call = calls[0]
    assert call["head"] == t, (call, t)
    assert set(call["paths"]) == _changed(lr, p, t), call
    assert call["baseline_sha256"] == hashlib.sha256(baseline).hexdigest(), call
    scratch = Path(call["cwd"]).resolve()
    assert not scratch.exists(), f"the scratch worktree {scratch} stayed"
    assert scratch not in rec.worktrees(lr)
    assert (lr.repo / BASELINE).read_bytes() == baseline


@pytest.mark.timeout(SLOW_S)
def test_land_prepare_skips_the_scan_without_a_baseline(tmp_path: Path) -> None:
    lr = rec.lane_rig(tmp_path)
    scanner = _scanner(tmp_path)
    proc = rec.prepare(lr, env=scanner.env)
    rec.ok(proc)
    assert _secrets_lines(proc) == ["secrets_skip:no_baseline"], proc.stdout
    assert _journal_secrets(lr) == ["secrets_skip:no_baseline"]
    assert scanner.calls() == []


@pytest.mark.timeout(SLOW_S)
def test_a_new_secret_in_a_lane_file_refuses_the_land(tmp_path: Path) -> None:
    lr = _secrets_lane(tmp_path, {BASELINE: _baseline_bytes()})
    creds = f"src/{lr.plan}/creds.py"
    _lane_commit(lr, {creds: b'PLANTED = "lane-secret-1"\n'}, "lane: credentials")
    scanner = _scanner(tmp_path)
    p = rec.main_ref(lr)
    proc = rec.prepare(lr, env=scanner.env)
    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    assert f"land_fail:secrets:{creds}" in _stripped(proc), (proc.stdout, proc.stderr)
    assert not any(line.startswith("land_ready:") for line in proc.stdout.splitlines())
    calls = scanner.calls()
    assert len(calls) == 1 and creds in calls[0]["paths"], calls
    after = rec.publish(lr)
    assert after.returncode != 0, (after.stdout, after.stderr)
    assert rec.main_ref(lr) == p, "a publish followed the refused scan"


@pytest.mark.timeout(SLOW_S)
def test_a_pure_line_move_is_recorded_and_the_land_goes_on(tmp_path: Path) -> None:
    rig_plan = "2026-10-17-fixture-plan"
    moved = f"src/{rig_plan}/moved.py"
    entry = {
        "type": "Planted Fixture",
        "filename": moved,
        "hashed_secret": hashlib.sha1(b"moved-value").hexdigest(),
        "is_verified": False,
        "line_number": 1,
    }
    baseline = _baseline_bytes({moved: [entry]})
    original = b'PLANTED = "moved-value"\n'
    lr = _secrets_lane(tmp_path, {BASELINE: baseline, moved: original})
    assert lr.plan == rig_plan, lr.plan
    _lane_commit(lr, {moved: b"# one\n# two\n" + original}, "lane: move the lines")
    scanner = _scanner(tmp_path)
    proc = rec.prepare(lr, env=scanner.env)
    tree = rec.ready_tree(proc)
    assert _secrets_lines(proc) == ["secrets_lines_moved:1"], proc.stdout
    assert _journal_secrets(lr) == ["secrets_lines_moved:1"]
    kept = rec.kept_refs(lr)
    assert _blob(lr, kept["T"], BASELINE) == _blob(lr, kept["L1"], BASELINE)
    assert (lr.repo / BASELINE).read_bytes() == baseline
    rec.record_verdict(lr, tree)
    rec.ok(rec.publish(lr))
    assert _blob(lr, rec.main_ref(lr), BASELINE) == _blob(lr, lr.p, BASELINE)


@pytest.mark.timeout(SLOW_S)
@pytest.mark.parametrize(
    "baseline",
    [b"{not json\n", b'{"version": "1.5.0"}\n'],
    ids=["not_json", "no_results"],
)
def test_an_unreadable_baseline_refuses_the_land(
    tmp_path: Path, baseline: bytes
) -> None:
    lr = _secrets_lane(tmp_path, {BASELINE: baseline})
    scanner = _scanner(tmp_path)
    proc = rec.prepare(lr, env=scanner.env)
    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    assert "land_fail:secrets:baseline_unreadable" in _stripped(proc), proc.stdout


def test_the_scanner_entry_is_one_documented_module_name() -> None:
    lanes = _lanes_module()
    assert lanes.SCAN_ENTRY_ENV == SCAN_ENV
    entry = lanes.SCAN_ENTRY
    assert isinstance(entry, (list, tuple)) and entry, entry
    assert all(isinstance(item, str) for item in entry), entry  # pyright: ignore[reportUnknownVariableType]
    assert "{paths}" in entry, entry
    assert SCAN_ENV in (lanes.__doc__ or ""), "the module docstring names the seam"


# ---------------------------------------------------------------------------
# a meu-status request carries the rendered BUILD_PLAN mark
# ---------------------------------------------------------------------------


def _integrated(
    tmp_path: Path, rows: Callable[[integ.Land], integ.Rows]
) -> tuple[integ.Land, str, str]:
    """Setup only: ``integ._build``, one lane commit, main moved, prepared; (land, T, L1)."""
    land = integ._build(tmp_path)  # pyright: ignore[reportPrivateUsage]
    integ._lane_commit(land, rows(land))  # pyright: ignore[reportPrivateUsage]
    integ._move_main(land)  # pyright: ignore[reportPrivateUsage]
    proc = integ._prepare(land, env=_scanner(tmp_path).env)  # pyright: ignore[reportPrivateUsage]
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    journal = integ._journal(land)  # pyright: ignore[reportPrivateUsage]
    return land, str(journal["T"]), str(journal["L1"])


def _render_check(land: integ.Land, tmp_path: Path, rev: str) -> None:
    """``meu_status.py render --check`` in a detached view of ``rev`` (as ``_run_tool``)."""
    view = tmp_path / "t-view"
    land.rig.git("worktree", "add", "-q", "--detach", str(view), rev)
    env = dict(bf.git_env(), PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    proc = subprocess.run(
        [sys.executable, str(view / "tools" / "meu_status.py"), "render", "--check"],
        cwd=str(view),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
        env=env,
        timeout=CHILD_TIMEOUT_S,
        check=False,
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr)


@pytest.mark.timeout(SLOW_S)
def test_a_meu_status_request_lands_the_rendered_build_plan_mark(
    tmp_path: Path,
) -> None:
    """Guard (``_regenerate`` already renders): T carries the rendered mark."""

    def rows(land: integ.Land) -> integ.Rows:
        return [(land.rid(1), f"meu-status {land.meu_row} -> {land.meu_target}")]

    land, t, l1 = _integrated(tmp_path, rows)
    assert integ._blob(land, t, BUILD_PLAN) != integ._blob(land, l1, BUILD_PLAN)  # pyright: ignore[reportPrivateUsage]
    _render_check(land, tmp_path, t)


@pytest.mark.timeout(SLOW_S)
def test_without_a_meu_status_request_the_build_plan_blob_is_l1s(
    tmp_path: Path,
) -> None:
    """Guard: no ``meu-status`` request leaves BUILD_PLAN.md as the lane had it."""

    def rows(land: integ.Land) -> integ.Rows:
        return [(land.rid(1), f"metrics-row {integ.LANE_ROW}")]

    land, t, l1 = _integrated(tmp_path, rows)
    assert integ._blob(land, t, BUILD_PLAN) == integ._blob(land, l1, BUILD_PLAN)  # pyright: ignore[reportPrivateUsage]


# ---------------------------------------------------------------------------
# a credits worktree (run identity) keeps the old route
# ---------------------------------------------------------------------------


def test_ea20_credits_worktree_keeps_the_old_route_under_required(
    exec_rig: ExecRig,
) -> None:
    """A worktree made with the run identity creates and lands as before."""
    exec_rig.policy(True, ["mal-s2b"])
    wt = exec_rig.create(
        "run-c", "--run-id", "run-c", "--op", "run-c-exec", "--plan", "plan-c"
    )
    ewl._write(wt, {"pkg/new_work.py": b"NEW = 1\n"})  # pyright: ignore[reportPrivateUsage]
    code, lines, err = exec_rig.call("land", wt)
    assert (code, lines) == (0, ["land_ok:1:0:0"]), (lines, err)
    landed = (exec_rig.src / "pkg/new_work.py").read_bytes().replace(b"\r\n", b"\n")
    assert landed == b"NEW = 1\n"


def test_ea20_partial_identity_under_required_makes_nothing(
    exec_rig: ExecRig,
) -> None:
    """Guard: a partial identity is not a credits worktree; nothing is made."""
    exec_rig.policy(True, ["mal-s2b"])
    heads = ewl._heads(exec_rig.src)  # pyright: ignore[reportPrivateUsage]
    code, lines, err = exec_rig.call("create", "run-d", "--run-id", "run-d")
    assert code == 1, (code, lines, err)
    assert lines in (["worktree_bad:identity"], ["worktree_bad:no_plan"]), (lines, err)
    exec_rig.assert_nothing_left("run-d", heads)


# ---------------------------------------------------------------------------
# A repeated key, staged-only work, an inherited SKIP and the H2-3c route token
# ---------------------------------------------------------------------------

# A scanner that records the SKIP value it inherits and finds nothing.
SKIP_SCANNER = r'''
"""SKIP probe of core/tools/tests/test_lane_route_tooling.py."""
import json
import os
import sys
from pathlib import Path

with Path(__LOG__).open("a", encoding="utf-8") as out:
    out.write(json.dumps({"skip": os.environ.get("SKIP")}) + "\n")
sys.exit(0)
'''


def test_lane_route_refuses_a_repeated_key(tmp_path: Path) -> None:
    """A repeated key is refused; JSON keeps only the last value of it."""
    tool = _executor()
    _write_policy(
        tmp_path,
        b'{"schema":"lane-route/1","required":true,"required":false,"exempt":[]}',
    )
    with pytest.raises(tool._Refusal) as caught:
        tool._lane_route(tmp_path)
    assert caught.value.lines == ["lane_route_bad:key_repeated:required"]


def test_create_refuses_a_repeated_required_key_and_makes_nothing(
    exec_rig: ExecRig,
) -> None:
    """A repeated key: ``required: true`` then ``false`` does not turn the refusals off."""
    _write_policy(
        exec_rig.src,
        b'{"schema":"lane-route/1","required":true,"required":false,"exempt":[]}',
    )
    heads = ewl._heads(exec_rig.src)  # pyright: ignore[reportPrivateUsage]
    code, lines, err = exec_rig.call("create", "lane-ambiguous")
    assert (code, lines) == (1, ["lane_route_bad:key_repeated:required"]), (lines, err)
    exec_rig.assert_nothing_left("lane-ambiguous", heads)


def test_remove_refuses_staged_only_work_on_the_old_route(exec_rig: ExecRig) -> None:
    """Content that only the index holds keeps the worktree (old route)."""
    exec_rig.policy(True, ["lane-o"])
    wt = exec_rig.create("lane-o")
    rel = "pkg/new_work.py"
    ewl._write(wt, {rel: b"NEW = 1\n"})  # pyright: ignore[reportPrivateUsage]
    assert exec_rig.call("land", wt)[:2] == (0, ["land_ok:1:0:0"])
    ewl._write(wt, {rel: b"STAGED_ONLY = 3\n"})  # pyright: ignore[reportPrivateUsage]
    added = ewl._git_proc(wt, "add", "--", rel)  # pyright: ignore[reportPrivateUsage]
    assert added.returncode == 0, added.stderr
    ewl._write(wt, {rel: b"NEW = 1\n"})  # pyright: ignore[reportPrivateUsage]
    code, lines, err = exec_rig.call("remove", wt)
    assert (code, lines) == (1, [f"worktree_bad:staged:{rel}"]), (lines, err)
    assert ewl._listed(exec_rig.src, wt) and wt.is_dir()  # pyright: ignore[reportPrivateUsage]
    shown = ewl._git_proc(wt, "show", f":{rel}")  # pyright: ignore[reportPrivateUsage]
    assert shown.stdout.replace(b"\r\n", b"\n") == b"STAGED_ONLY = 3\n"


def test_remove_with_discard_still_deletes_staged_only_work(exec_rig: ExecRig) -> None:
    """Guard: ``--discard`` is the one way to drop such a worktree."""
    exec_rig.policy(True, ["lane-o"])
    wt = exec_rig.create("lane-o")
    rel = "pkg/new_work.py"
    ewl._write(wt, {rel: b"STAGED_ONLY = 3\n"})  # pyright: ignore[reportPrivateUsage]
    assert ewl._git_proc(wt, "add", "--", rel).returncode == 0  # pyright: ignore[reportPrivateUsage]
    (wt / rel).unlink()
    code, lines, err = exec_rig.call("remove", wt, "--discard")
    assert (code, lines) == (0, [f"worktree_removed:{wt.as_posix()}"]), (lines, err)
    assert not ewl._listed(exec_rig.src, wt)  # pyright: ignore[reportPrivateUsage]


@pytest.mark.timeout(SLOW_S)
def test_remove_refuses_staged_only_work_on_the_lane_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    """After a publish, a staged change with the file put back keeps the worktree."""
    route = _route_rig(tmp_path, monkeypatch, capfd)
    _published(route)
    target = route.wt / route.lr.changed
    original = target.read_bytes()
    target.write_bytes(b"IMPORTANT_STAGED_WORK = 1\n")
    rec.git(route.wt, "add", "--", route.lr.changed)
    target.write_bytes(original)
    assert (
        rec.git(route.wt, "show", f":{route.lr.changed}") == "IMPORTANT_STAGED_WORK = 1"
    )
    code, lines, err = route.remove()
    assert (code, lines) == (1, [f"worktree_bad:staged:{route.lr.changed}"]), (
        lines,
        err,
    )
    assert route.wt.resolve() in rec.worktrees(route.lr)
    assert (
        rec.git(route.wt, "show", f":{route.lr.changed}") == "IMPORTANT_STAGED_WORK = 1"
    )


@pytest.mark.timeout(SLOW_S)
def test_land_prepare_scans_without_an_inherited_skip(tmp_path: Path) -> None:
    """Pre-commit's SKIP never reaches the scanner child."""
    lr = _secrets_lane(tmp_path, {BASELINE: _baseline_bytes()})
    log = tmp_path / "skip-scanner" / "calls.jsonl"
    script = tmp_path / "skip-scanner" / "skip_hook.py"
    script.parent.mkdir(parents=True)
    script.write_text(
        SKIP_SCANNER.replace("__LOG__", repr(str(log))), encoding="utf-8", newline="\n"
    )
    entry = json.dumps([sys.executable, str(script), "{paths}"])
    proc = rec.prepare(lr, env={SCAN_ENV: entry, "SKIP": "detect-secrets"})
    rec.ok(proc)
    calls = [json.loads(line) for line in log.read_text("utf-8").splitlines() if line]
    assert calls == [{"skip": None}], calls


# ---------------------------------------------------------------------------
# Execution review round 2 (R2-1): the scan reads T's pre-commit config bytes
# ---------------------------------------------------------------------------

# A scanner that records the config bytes it sees and finds nothing (R2-1).
CONFIG_SCANNER = r'''
"""Config probe of core/tools/tests/test_lane_route_tooling.py."""
import json
import sys
from pathlib import Path

args = sys.argv[1:]
given = Path(args[args.index("--config") + 1])
tree = Path(".pre-commit-config.yaml")
with Path(__LOG__).open("a", encoding="utf-8") as out:
    out.write(json.dumps({
        "tree": tree.read_text("utf-8") if tree.is_file() else None,
        "given": given.read_text("utf-8") if given.is_file() else None,
        "given_path": given.as_posix(),
    }) + "\n")
sys.exit(0)
'''
P_CONFIG = "repos: []\n# P's scanner configuration\n"
T_CONFIG = "repos: []\n# the lane's own configuration\n"


def _config_lane(tmp_path: Path, extra: dict[str, bytes]) -> rec.LaneRig:
    """Setup only: ``_secrets_lane`` whose plan also owns the pre-commit config."""
    rig = b3.rig(tmp_path / "fx", ROOT, seed=lwc.SEED)
    rig.bind()
    rec.seed_plan(rig, rig.plan, {rec.METRICS: rec.METRICS_HEAD.encode(), **extra})
    task = rec.ensure_task(rig, rig.plan)
    text = task.read_text(encoding="utf-8")
    assert "owns:\n" in text, "the fixture task.md has no owns list"
    text = text.replace("owns:\n", f"owns:\n  - {PRE_COMMIT_CONFIG}\n", 1)
    rig.seed(
        {task.relative_to(rig.repo).as_posix(): text.encode("utf-8")},
        "fixture: own the scanner config",
    )
    return rec.open_lane(rig, tmp_path, rig.plan, rec.CARD_SESSION)


def _config_scan(tmp_path: Path) -> tuple[subprocess.CompletedProcess[str], list[Any]]:
    """Prepare a lane that changes the config, under the config probe; (proc, calls)."""
    lr = _config_lane(
        tmp_path,
        {BASELINE: _baseline_bytes(), PRE_COMMIT_CONFIG: P_CONFIG.encode("utf-8")},
    )
    _lane_commit(lr, {PRE_COMMIT_CONFIG: T_CONFIG.encode("utf-8")}, "lane: config")
    log = tmp_path / "config-scanner" / "calls.jsonl"
    script = tmp_path / "config-scanner" / "config_hook.py"
    script.parent.mkdir(parents=True)
    script.write_text(
        CONFIG_SCANNER.replace("__LOG__", repr(str(log))),
        encoding="utf-8",
        newline="\n",
    )
    entry = json.dumps([sys.executable, str(script), "--config", "{config}", "{paths}"])
    proc = rec.prepare(lr, env={SCAN_ENV: entry})
    calls = [json.loads(line) for line in log.read_text("utf-8").splitlines() if line]
    return proc, calls


def test_the_default_scanner_entry_takes_ps_config_as_an_option() -> None:
    """R2-1: the default entry names P's config by ``--config``, not by its path."""
    lanes = _lanes_module()
    entry = list(lanes.SCAN_ENTRY)
    assert lanes.SCAN_CONFIG_ARG in entry, entry
    at = entry.index(lanes.SCAN_CONFIG_ARG)
    assert entry[at - 1] == "--config", entry
    assert entry.index("run") < at < entry.index("--files"), entry


@pytest.mark.timeout(SLOW_S)
def test_the_scan_keeps_ts_config_and_passes_ps_config_apart(tmp_path: Path) -> None:
    """R2-1: the scanned tree holds T's config bytes; P's config is a separate file."""
    proc, calls = _config_scan(tmp_path)
    rec.ok(proc)
    assert len(calls) == 1, calls
    call = calls[0]
    assert call["tree"] == T_CONFIG, call
    assert call["given"] == P_CONFIG, call
    assert not call["given_path"].endswith(f"-scan/{PRE_COMMIT_CONFIG}"), call
    assert not Path(call["given_path"]).exists(), "the separate config is removed"


@pytest.mark.timeout(SLOW_S)
def test_a_config_entry_without_ps_config_skips_the_scan(tmp_path: Path) -> None:
    """R2-1 guard: an entry that needs P's config, and P has none, skips the scan."""
    lr = _secrets_lane(tmp_path, {BASELINE: _baseline_bytes()})
    entry = json.dumps(
        [sys.executable, "-c", "pass", "--config", "{config}", "{paths}"]
    )
    proc = rec.prepare(lr, env={SCAN_ENV: entry})
    rec.ok(proc)
    assert _secrets_lines(proc) == ["secrets_skip:no_config"], proc.stdout


def _landed_query(exec_rig: ExecRig, wt: Path) -> list[str]:
    proc = exec_rig.tool._run_lanes(exec_rig.src, "landed", "--worktree", str(wt))
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def test_landed_query_of_an_old_route_worktree_is_no_card(exec_rig: ExecRig) -> None:
    """Guard: the token the H2-3c Validation command keys the old route on."""
    exec_rig.policy(True, ["lane-o"])
    wt = exec_rig.create("lane-o")
    assert _landed_query(exec_rig, wt) == ["not_landed:no_card"]


def test_landed_query_of_an_unpublished_lane_worktree_is_not_no_card(
    exec_rig: ExecRig,
) -> None:
    """Guard: a default lane before its publish is neither route of H2-3c."""
    exec_rig.lane_plan(["pkg/lane/"])
    exec_rig.policy(True, [])
    wt = exec_rig.create("lane-default", "--lane-plan", LANE_PLAN, "--session", SESSION)
    shown = _landed_query(exec_rig, wt)
    assert len(shown) == 1 and shown[0].startswith("not_landed:"), shown
    assert shown != ["not_landed:no_card"], shown
