"""MEU-785 WP-C Red: the stop gate in a lane worktree (AC-785.28).

``tools/stop_gate.py`` uses the root it is given, else the cwd (``main``,
``tools/stop_gate.py:1003``). A lane session's root is the lane worktree, so plan
discovery (``_tree_plans``, ``:525``) and the active-plan selection read that root and
never the main tree (design D:276). A lane root without plans takes the existing
no-active-plan path. The existing stop-gate tests (``test_stop_gate.py``,
``test_stop_gate_done.py``, ``test_stop_gate_run_parameters.py``) stay unchanged.

Fixture: a real temporary repository (``git init -b main``) with a linked lane
worktree; the main tree and the lane each hold their own plan folders.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from tools.tests.run_parameters_fixtures import build_fixture as bf
from tools import stop_gate

PLANS = Path("docs") / "execution" / "plans"
SESSION = "sess-lane-1"
MAIN_PLAN = "2026-10-23-main-open"
LANE_PLAN = "2026-10-23-lane-open"

_TASK_OPEN = """\
---
project: "{slug}"
status: "in_progress"
stop_gate: "armed"
template_version: "2.1"
{extra}---

# Task — {slug}

| # | Task | Owner | Deliverable | Validation | Status |
|---|------|-------|-------------|------------|--------|
| 1 | Implement thing | coder | code | `rtk pytest` | `[x]` |
| H1-6 | Create handoff | reviewer | handoff.md | `rtk rg "Evidence" h.md` | `[ ]` |
"""

_STOP_PAYLOAD = json.dumps(
    {"session_id": SESSION, "hook_event_name": "Stop", "stop_hook_active": False}
)


def _task(slug: str, extra: str = "") -> str:
    return _TASK_OPEN.format(slug=slug, extra=extra)


def _make_plan(root: Path, slug: str, body: str) -> Path:
    folder = root / PLANS / slug
    folder.mkdir(parents=True, exist_ok=True)
    task = folder / "task.md"
    task.write_text(body, encoding="utf-8")
    return task


def _repo_with_lane(tmp_path: Path) -> tuple[Path, Path]:
    """A main tree with one commit and a linked worktree on ``lane/x``."""
    main = tmp_path / "main"
    main.mkdir()
    bf.git(main, "init", "-q", "-b", "main")
    (main / "README.md").write_text("fixture\n", encoding="utf-8")
    bf.git(main, "add", "README.md")
    bf.git(
        main,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-q",
        "-m",
        "fixture: seed",
    )
    lane = tmp_path / "lane"
    bf.git(main, "worktree", "add", "-q", "-b", "lane/x", str(lane), "HEAD")
    return main, lane


def _run_main(monkeypatch: pytest.MonkeyPatch, receipts: Path, argv: list[str]) -> int:
    monkeypatch.setenv("{{PROJECT_NAME_UPPER}}_RECEIPTS", str(receipts))
    monkeypatch.setattr(sys, "stdin", io.StringIO(_STOP_PAYLOAD))
    return stop_gate.main(argv)


def test_lane_root_argument_reads_the_lane_plans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-785.28: the given lane root is the plan root; the main tree's plan is not read."""
    main, lane = _repo_with_lane(tmp_path)
    _make_plan(main, MAIN_PLAN, _task(MAIN_PLAN))
    lane_task = _make_plan(lane, LANE_PLAN, _task(LANE_PLAN))
    code = _run_main(monkeypatch, tmp_path / "receipts", [str(lane)])
    out = capsys.readouterr().out
    assert code == 0
    verdict = json.loads(out)
    assert verdict["decision"] == "block", verdict
    assert LANE_PLAN in verdict["reason"], verdict
    assert MAIN_PLAN not in verdict["reason"], verdict
    detail = stop_gate.evaluate_detail(lane)
    assert (detail[2], detail[4]) == ("open_rows", lane_task.as_posix()), detail


def test_cwd_fallback_in_a_lane_reads_the_lane_plans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-785.28: with no root argument the cwd (the lane worktree) is the plan root."""
    main, lane = _repo_with_lane(tmp_path)
    _make_plan(main, MAIN_PLAN, _task(MAIN_PLAN))
    _make_plan(lane, LANE_PLAN, _task(LANE_PLAN))
    monkeypatch.chdir(lane)
    code = _run_main(monkeypatch, tmp_path / "receipts", [])
    verdict = json.loads(capsys.readouterr().out)
    assert code == 0
    assert verdict["decision"] == "block", verdict
    assert LANE_PLAN in verdict["reason"] and MAIN_PLAN not in verdict["reason"], (
        verdict
    )


def test_lane_root_without_plans_takes_the_no_plan_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-785.28 edge: a lane root without plans allows the stop; the main tree is not read."""
    main, lane = _repo_with_lane(tmp_path)
    _make_plan(main, MAIN_PLAN, _task(MAIN_PLAN))
    assert not (lane / PLANS).exists()
    done, reason, kind, rows, task_file = stop_gate.evaluate_detail(lane)
    assert (done, kind, rows, task_file) == (True, "no_active_plan", 0, None), reason
    assert MAIN_PLAN not in reason, reason
    code = _run_main(monkeypatch, tmp_path / "receipts", [str(lane)])
    assert code == 0
    assert capsys.readouterr().out == "", "a stop is allowed by an empty stdout"


def test_plan_discovery_reads_the_lane_root(tmp_path: Path) -> None:
    """AC-785.28: ``_tree_plans`` reads the ``bound_sessions`` copies under the given root."""
    main, lane = _repo_with_lane(tmp_path)
    bound = f'bound_sessions: ["{SESSION}"]\n'
    _make_plan(main, MAIN_PLAN, _task(MAIN_PLAN, bound))
    _make_plan(lane, LANE_PLAN, _task(LANE_PLAN, bound))
    assert stop_gate._tree_plans(lane, SESSION) == ([LANE_PLAN], True)
    assert stop_gate._tree_plans(main, SESSION) == ([MAIN_PLAN], True)
