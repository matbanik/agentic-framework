"""G-4: ``released:done`` is a sanctioned stop in tools/stop_gate.py.

Plan: docs/execution/plans/2026-10-15-scheduled-credits-runs (Component A,
AC-A.4; report R§2.3 G-4, R§7.4). The main-tree ``task.md`` files record
``stop_gate: "released:done"`` at closeout, so the hook must accept ``done`` with
no warning. A reason outside the closed set (``blocked-resources``) keeps the
existing unknown-value warning path.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

from tools import stop_gate

_TASK_OPEN = """\
---
project: "2026-10-15-demo"
status: "in_progress"
stop_gate: "armed"
template_version: "2.1"
---

# Task — Demo

| # | Task | Owner | Deliverable | Validation | Status |
|---|------|-------|-------------|------------|--------|
| 1 | Implement thing | coder | code | `rtk pytest *> out.txt` | `[x]` |
| H1-6 | Create handoff | reviewer | handoff.md | `rtk rg "Evidence" h.md` | `[ ]` |
"""

_STOP_PAYLOAD = (
    '{"session_id": "sess-1", "hook_event_name": "Stop", "stop_hook_active": false}'
)


def _make_plan(repo: Path, slug: str, body: str) -> Path:
    folder = repo / "docs" / "execution" / "plans" / slug
    folder.mkdir(parents=True, exist_ok=True)
    task = folder / "task.md"
    task.write_text(body, encoding="utf-8")
    return task


def _released(reason: str) -> str:
    return _TASK_OPEN.replace('stop_gate: "armed"', f'stop_gate: "released:{reason}"')


def _run_main(monkeypatch: pytest.MonkeyPatch, repo: Path, stdin_text: str) -> int:
    """Run ``main()`` with ``stdin_text``; the block counter stays under ``repo``.

    tests/conftest.py sets ``AGENT_NOTIFY=off`` for the session, so no notice is sent.
    """
    monkeypatch.setenv("{{PROJECT_NAME_UPPER}}_RECEIPTS", str(repo / "receipts"))
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_text))
    return stop_gate.main([str(repo)])


def test_ac_a4_done_is_a_release_reason() -> None:
    """AC-A.4: ``done`` is in the closed set; the four existing reasons stay."""
    assert "done" in stop_gate.RELEASE_REASONS
    for reason in ("round-cap", "reviewer-unavailable", "human-gate", "handback"):
        assert reason in stop_gate.RELEASE_REASONS
    assert stop_gate.release_reason("released:done") == "done"


def test_ac_a4_released_done_allows_stop_without_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-A.4: ``released:done`` lets the turn end and prints no unknown-value warning."""
    task = _make_plan(tmp_path, "2026-10-15-done", _released("done"))

    assert stop_gate.find_active_task_file(tmp_path) == task
    done, verdict = stop_gate.evaluate(tmp_path)
    assert done is True
    assert "released:done" in verdict
    err = capsys.readouterr().err
    assert "unknown stop_gate value" not in err

    code = _run_main(monkeypatch, tmp_path, _STOP_PAYLOAD)
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out == ""
    assert "released:done" in captured.err
    assert "unknown stop_gate value" not in captured.err


def test_ac_a4_negative_blocked_resources_keeps_warning_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-A.4 negative: ``released:blocked-resources`` is still an unknown value."""
    task = _make_plan(tmp_path, "2026-10-15-odd", _released("blocked-resources"))

    assert "blocked-resources" not in stop_gate.RELEASE_REASONS
    assert stop_gate.release_reason("released:blocked-resources") is None
    assert stop_gate.find_active_task_file(tmp_path) is None
    err = capsys.readouterr().err
    assert "unknown stop_gate value" in err
    assert "released:blocked-resources" in err
    assert task.name in err
