"""Unit tests for tools/stop_gate.py — the deterministic Stop-hook gate.

These verify the harness-agnostic decision logic: front-matter status parsing,
status-cell detection (robust to escaped pipes in validation commands, immune
to the Status Legend and phase-divider rows), active-plan selection by mtime
among *armed* plans, the release marker, the ``main()`` payload contract, and
the overall evaluate() verdict.

Arming (plan D-5, project ``2026-09-25-agents-md-model-refresh-rewrite``): a plan
is gated only when its leading frontmatter carries BOTH ``status: "in_progress"``
AND ``stop_gate: "armed"``; ``stop_gate: "released:<reason>"`` records one of the
four sanctioned stops and lets the turn end.
"""

from __future__ import annotations

import importlib
import io
import json
import os
import sys
import types
from pathlib import Path

import pytest

from tools import stop_gate

# A realistic task.md fragment exercising every row shape the parser must handle.
_TASK_DONE = """\
---
project: "2026-06-22-demo"
status: "in_progress"
stop_gate: "armed"
template_version: "2.1"
---

# Task — Demo

| # | Task | Owner | Deliverable | Validation | Status |
|---|------|-------|-------------|------------|--------|
| 1 | Implement thing | coder | code | `rtk pytest *> out.txt; Get-Content out.txt \\| Select-Object -Last 5` | `[x]` |
| | **📋 Phase H1 — Pre-Review Closeout** (do not stop) | | | | |
| H1-6 | Create handoff | reviewer | handoff.md | `rtk rg "Evidence" h.md` | `[x]` |

### Status Legend

| Symbol | Meaning |
|--------|---------|
| `[ ]` | Not started |
| `[/]` | In progress |
| `[x]` | Complete |
"""

_TASK_OPEN = _TASK_DONE.replace("| `[x]` |\n| | **📋", "| `[/]` |\n| | **📋").replace(
    '| H1-6 | Create handoff | reviewer | handoff.md | `rtk rg "Evidence" h.md` | `[x]` |',
    '| H1-6 | Create handoff | reviewer | handoff.md | `rtk rg "Evidence" h.md` | `[ ]` |',
)

_TASK_OPEN_UNARMED = _TASK_OPEN.replace('stop_gate: "armed"\n', "")

_STOP_PAYLOAD = (
    '{"session_id": "sess-1", "hook_event_name": "Stop", "stop_hook_active": false}'
)


def _make_plan(repo: Path, slug: str, body: str) -> Path:
    folder = repo / "docs" / "execution" / "plans" / slug
    folder.mkdir(parents=True, exist_ok=True)
    task = folder / "task.md"
    task.write_text(body, encoding="utf-8")
    return task


def _run_main(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    stdin_text: str,
    argv: list[str] | None = None,
) -> int:
    """Run ``main()`` with ``stdin_text`` and receipts under ``tmp_path``."""
    monkeypatch.setenv("{{PROJECT_NAME_UPPER}}_RECEIPTS", str(tmp_path / "receipts"))
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_text))
    return stop_gate.main([str(tmp_path)] if argv is None else argv)


def _counter_files(tmp_path: Path) -> list[Path]:
    receipts = tmp_path / "receipts"
    return sorted(receipts.glob("stop_gate_*.count")) if receipts.exists() else []


# --- parsing ------------------------------------------------------------------------------


def test_frontmatter_status_only_reads_leading_block() -> None:
    assert stop_gate.frontmatter_status(_TASK_DONE) == "in_progress"
    assert (
        stop_gate.frontmatter_status("no frontmatter here\nstatus: in_progress") is None
    )


def test_status_cell_ignores_legend_and_dividers() -> None:
    # Legend row: open marker is in the FIRST cell, meaning in the last -> not open.
    assert stop_gate._status_cell("| `[ ]` | Not started |") == "Not started"
    # Divider row: empty status cell -> None.
    assert stop_gate._status_cell("| | **Phase H1** | | | | |") is None
    # Separator row -> None.
    assert stop_gate._status_cell("|---|---|---|") is None
    # Real status cell, even with an escaped pipe earlier in the row.
    assert stop_gate._status_cell("| 1 | x | `a \\| b` | `[x]` |") == "[x]"


def test_count_open_rows_handles_escaped_pipes_and_markers() -> None:
    done_rows = stop_gate.count_open_rows(_TASK_DONE)
    assert done_rows == []  # only [x] rows + legend, nothing open

    open_rows = stop_gate.count_open_rows(_TASK_OPEN)
    idents = sorted(r.ident for r in open_rows)
    assert idents == ["1", "H1-6"]
    assert {r.marker for r in open_rows} == {"[/]", "[ ]"}


# --- evaluate -----------------------------------------------------------------------------


def test_evaluate_no_plan_allows_stop(tmp_path: Path) -> None:
    done, reason = stop_gate.evaluate(tmp_path)
    assert done is True
    assert "No in_progress plan" in reason


def test_evaluate_open_rows_blocks(tmp_path: Path) -> None:
    _make_plan(tmp_path, "2026-06-22-open", _TASK_OPEN)
    done, reason = stop_gate.evaluate(tmp_path)
    assert done is False
    assert "unchecked row" in reason
    assert "sanctioned stops" in reason


def test_evaluate_all_checked_allows_stop(tmp_path: Path) -> None:
    _make_plan(tmp_path, "2026-06-22-done", _TASK_DONE)
    done, _ = stop_gate.evaluate(tmp_path)
    assert done is True


def test_completed_status_plan_is_not_active(tmp_path: Path) -> None:
    _make_plan(
        tmp_path,
        "2026-06-22-old",
        _TASK_OPEN.replace('status: "in_progress"', 'status: "complete"'),
    )
    done, reason = stop_gate.evaluate(tmp_path)
    assert done is True
    assert "No in_progress plan" in reason


def test_most_recent_in_progress_plan_wins(tmp_path: Path) -> None:
    older = _make_plan(
        tmp_path, "2026-06-20-stale", _TASK_DONE
    )  # in_progress, all done
    newer = _make_plan(
        tmp_path, "2026-06-22-active", _TASK_OPEN
    )  # in_progress, has open rows
    # Force the "done" plan to look older than the "open" plan.
    os.utime(older, (1_000_000, 1_000_000))
    os.utime(newer, (2_000_000, 2_000_000))
    assert stop_gate.find_active_task_file(tmp_path) == newer
    done, _ = stop_gate.evaluate(tmp_path)
    assert done is False


def test_block_counter_releases_after_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("{{PROJECT_NAME_UPPER}}_RECEIPTS", str(tmp_path / "receipts"))
    path = stop_gate._counter_path("sess-1")
    for value in range(1, stop_gate.MAX_CONSECUTIVE_BLOCKS + 1):
        stop_gate._write_counter(path, value)
        assert stop_gate._read_counter(path) == value
    stop_gate._clear_counter(path)
    assert stop_gate._read_counter(path) == 0


# --- arming and release (plan D-5) --------------------------------------------------------


def test_unarmed_in_progress_plan_is_ignored(tmp_path: Path) -> None:
    _make_plan(tmp_path, "2026-06-22-unarmed", _TASK_OPEN_UNARMED)
    assert stop_gate.find_active_task_file(tmp_path) is None
    done, reason = stop_gate.evaluate(tmp_path)
    assert done is True
    assert "No in_progress plan" in reason


def test_armed_older_plan_beats_newer_unarmed(tmp_path: Path) -> None:
    armed = _make_plan(tmp_path, "2026-06-20-armed", _TASK_OPEN)
    unarmed = _make_plan(tmp_path, "2026-06-22-unarmed", _TASK_OPEN_UNARMED)
    os.utime(armed, (1_000_000, 1_000_000))
    os.utime(unarmed, (2_000_000, 2_000_000))
    assert stop_gate.find_active_task_file(tmp_path) == armed
    done, _ = stop_gate.evaluate(tmp_path)
    assert done is False


@pytest.mark.parametrize(
    "reason", ["round-cap", "reviewer-unavailable", "human-gate", "handback"]
)
def test_released_marker_allows_stop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    reason: str,
) -> None:
    body = _TASK_OPEN.replace('stop_gate: "armed"', f'stop_gate: "released:{reason}"')
    _make_plan(tmp_path, "2026-06-22-released", body)

    done, verdict = stop_gate.evaluate(tmp_path)
    assert done is True
    assert f"released:{reason}" in verdict

    code = _run_main(monkeypatch, tmp_path, _STOP_PAYLOAD)
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out == ""
    assert f"released:{reason}" in captured.err
    assert _counter_files(tmp_path) == []


def test_unknown_stop_gate_value_is_inert(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    body = _TASK_OPEN.replace('stop_gate: "armed"', 'stop_gate: "maybe"')
    plan = _make_plan(tmp_path, "2026-06-22-odd", body)
    assert stop_gate.find_active_task_file(tmp_path) is None
    err = capsys.readouterr().err
    assert "stop_gate" in err
    assert "maybe" in err
    assert plan.name in err
    done, _ = stop_gate.evaluate(tmp_path)
    assert done is True


# --- main() payload contract (plan D-5) ---------------------------------------------------


def test_main_blocks_on_armed_open_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_plan(tmp_path, "2026-06-22-open", _TASK_OPEN)
    code = _run_main(monkeypatch, tmp_path, _STOP_PAYLOAD)
    out = capsys.readouterr().out
    assert code == 0
    assert '"decision": "block"' in out
    assert "sanctioned stops" in out
    assert len(_counter_files(tmp_path)) == 1


def test_main_invalid_json_fails_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_plan(tmp_path, "2026-06-22-open", _TASK_OPEN)
    code = _run_main(monkeypatch, tmp_path, "not json {")
    assert code == 0
    assert capsys.readouterr().out == ""
    assert _counter_files(tmp_path) == []


@pytest.mark.parametrize("raw", ["[]", "null"])
def test_main_non_object_payload_fails_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    raw: str,
) -> None:
    _make_plan(tmp_path, "2026-06-22-open", _TASK_OPEN)
    code = _run_main(monkeypatch, tmp_path, raw)
    assert code == 0
    assert capsys.readouterr().out == ""
    assert _counter_files(tmp_path) == []


@pytest.mark.parametrize(
    "raw",
    [
        "{}",
        '{"hook_event_name": "PreToolUse", "session_id": "s"}',
        '{"hook_event_name": "Stop", "session_id": 7}',
    ],
    ids=["empty-object", "wrong-event", "non-string-session"],
)
def test_main_missing_session_fails_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    raw: str,
) -> None:
    _make_plan(tmp_path, "2026-06-22-open", _TASK_OPEN)
    code = _run_main(monkeypatch, tmp_path, raw)
    assert code == 0
    assert capsys.readouterr().out == ""
    assert _counter_files(tmp_path) == []


def test_main_empty_stdin_is_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_plan(tmp_path, "2026-06-22-open", _TASK_OPEN)
    code = _run_main(monkeypatch, tmp_path, "")
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out == ""
    assert "unchecked row" in captured.err
    assert _counter_files(tmp_path) == []


def test_main_uses_repo_root_arg_from_subdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_plan(tmp_path, "2026-06-22-open", _TASK_OPEN)
    subdir = tmp_path / "ui"
    subdir.mkdir()
    monkeypatch.chdir(subdir)
    code = _run_main(monkeypatch, tmp_path, _STOP_PAYLOAD, argv=[str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0
    assert '"decision": "block"' in out


def test_reason_names_four_stops(tmp_path: Path) -> None:
    _make_plan(tmp_path, "2026-06-22-open", _TASK_OPEN)
    done, reason = stop_gate.evaluate(tmp_path)
    assert done is False
    assert "four sanctioned stops" in reason
    assert "released:" in reason
    assert "five sanctioned turn-enders" not in reason
    assert "context checkpoint" not in reason


# --- decision log (execution amendment A-1, 2026-09-25) -----------------------------------


def _log_lines(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_main_appends_one_log_line_per_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Every Stop verdict leaves a durable JSON line in ``{{PROJECT_NAME_UPPER}}_HOOK_LOG``.

    The block counter is transient (cleared on release), so the smoke receipt counts
    these lines instead — the same evidence channel the PreToolUse hooks use.
    """
    log = tmp_path / "hooks.jsonl"
    monkeypatch.setenv("{{PROJECT_NAME_UPPER}}_HOOK_LOG", str(log))
    _make_plan(tmp_path, "2026-06-22-open", _TASK_OPEN)

    for _ in range(stop_gate.MAX_CONSECUTIVE_BLOCKS + 1):
        assert _run_main(monkeypatch, tmp_path, _STOP_PAYLOAD) == 0
    capsys.readouterr()
    lines = _log_lines(log)
    assert [line["decision"] for line in lines] == (
        ["block"] * stop_gate.MAX_CONSECUTIVE_BLOCKS + ["release"]
    )
    assert {line["hook"] for line in lines} == {"stop_gate"}
    assert {line["session_id"] for line in lines} == {"sess-1"}
    assert [line["blocks"] for line in lines] == list(
        range(1, stop_gate.MAX_CONSECUTIVE_BLOCKS + 2)
    )

    _make_plan(tmp_path, "2026-06-22-open", _TASK_DONE)
    assert _run_main(monkeypatch, tmp_path, _STOP_PAYLOAD) == 0
    capsys.readouterr()
    assert _log_lines(log)[-1] == {
        "hook": "stop_gate",
        "session_id": "sess-1",
        "decision": "allow",
        "blocks": 0,
    }


def test_main_without_hook_log_env_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("{{PROJECT_NAME_UPPER}}_HOOK_LOG", raising=False)
    _make_plan(tmp_path, "2026-06-22-open", _TASK_OPEN)
    assert _run_main(monkeypatch, tmp_path, _STOP_PAYLOAD) == 0
    capsys.readouterr()
    assert not list(tmp_path.glob("*.jsonl"))


# --- session ownership (2026-09-29) -------------------------------------------------------
#
# Concurrent sessions share one working tree. Without ownership, the newest armed plan
# in the repo gates *every* session's Stop, so a planning session is blocked by another
# session's closeout rows. A session owns a plan when its own transcript records a
# file-tool write inside that plan's folder; reading a plan does not claim it.


def _tool_use(name: str, tool_input: dict[str, object]) -> str:
    return json.dumps(
        {
            "type": "assistant",
            "isSidechain": False,
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "working"},
                    {"type": "tool_use", "id": "t", "name": name, "input": tool_input},
                ],
            },
        }
    )


def _transcript(tmp_path: Path, lines: list[str]) -> Path:
    path = tmp_path / "transcripts" / "sess-1.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    # A non-JSON line and a non-assistant entry must be skipped, not fatal.
    path.write_text(
        "\n".join(["not json {", '{"type": "user", "message": "hi"}', *lines]) + "\n",
        encoding="utf-8",
    )
    return path


def _payload_with(transcript: Path) -> str:
    return json.dumps(
        {
            "session_id": "sess-1",
            "hook_event_name": "Stop",
            "stop_hook_active": False,
            "transcript_path": str(transcript),
        }
    )


def test_owned_plan_dirs_counts_file_tool_writes_only(tmp_path: Path) -> None:
    mine = _make_plan(tmp_path, "2026-06-22-mine", _TASK_OPEN)
    theirs = _make_plan(tmp_path, "2026-06-22-theirs", _TASK_OPEN)
    notebook_plan = _make_plan(tmp_path, "2026-06-22-nb", _TASK_OPEN)
    transcript = _transcript(
        tmp_path,
        [
            _tool_use("Write", {"file_path": str(mine), "content": "x"}),
            _tool_use(
                "Edit",
                {
                    "file_path": str(mine.parent / "implementation-plan.md"),
                    "old_string": "a",
                    "new_string": "b",
                },
            ),
            _tool_use(
                "NotebookEdit", {"notebook_path": str(notebook_plan.parent / "n.ipynb")}
            ),
            # Reads, searches and shell mentions of another plan do not claim it.
            _tool_use("Read", {"file_path": str(theirs)}),
            _tool_use("Grep", {"pattern": "x", "path": str(theirs.parent)}),
            _tool_use("Bash", {"command": f"cat {theirs}"}),
            # A write outside every plan folder claims nothing.
            _tool_use(
                "Write", {"file_path": str(tmp_path / "notes.md"), "content": "x"}
            ),
        ],
    )
    owned = stop_gate.owned_plan_dirs(transcript, tmp_path)
    assert owned is not None
    assert {os.path.normcase(str(p)) for p in owned} == {
        os.path.normcase(str(mine.parent.resolve())),
        os.path.normcase(str(notebook_plan.parent.resolve())),
    }


def test_owned_plan_dirs_unreadable_transcript_is_none(tmp_path: Path) -> None:
    assert stop_gate.owned_plan_dirs(tmp_path / "missing.jsonl", tmp_path) is None


@pytest.mark.skipif(
    os.name != "nt", reason="case-insensitive paths are a Windows property"
)
def test_owned_plan_dirs_matches_case_insensitively_on_windows(tmp_path: Path) -> None:
    mine = _make_plan(tmp_path, "2026-06-22-mine", _TASK_OPEN)
    # The hook's repo root and the transcript's paths can differ in case (c:\ vs C:\).
    transcript = _transcript(
        tmp_path, [_tool_use("Edit", {"file_path": str(mine).upper()})]
    )
    owned = stop_gate.owned_plan_dirs(transcript, tmp_path)
    assert owned is not None and len(owned) == 1


def test_evaluate_skips_armed_plan_the_session_does_not_own(tmp_path: Path) -> None:
    foreign = _make_plan(tmp_path, "2026-06-22-foreign", _TASK_OPEN)
    own = _make_plan(tmp_path, "2026-06-20-own", _TASK_OPEN)
    os.utime(own, (1_000_000, 1_000_000))
    os.utime(foreign, (2_000_000, 2_000_000))  # the foreign plan is newer

    assert (
        stop_gate.find_active_task_file(tmp_path, owned={own.parent.resolve()}) == own
    )
    done, reason = stop_gate.evaluate(tmp_path, owned={own.parent.resolve()})
    assert done is False
    assert "2026-06-20-own" in reason
    assert "2026-06-22-foreign" not in reason

    done, reason = stop_gate.evaluate(tmp_path, owned=set())
    assert done is True
    assert "owned by this session" in reason


def test_main_does_not_block_on_another_sessions_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    foreign = _make_plan(tmp_path, "2026-06-22-foreign", _TASK_OPEN)
    transcript = _transcript(tmp_path, [_tool_use("Read", {"file_path": str(foreign)})])
    code = _run_main(monkeypatch, tmp_path, _payload_with(transcript))
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out == ""  # no block verdict
    assert "owned by this session" in captured.err
    assert _counter_files(tmp_path) == []


def test_main_blocks_on_the_sessions_own_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    own = _make_plan(tmp_path, "2026-06-22-own", _TASK_OPEN)
    transcript = _transcript(
        tmp_path,
        [
            _tool_use(
                "Edit", {"file_path": str(own), "old_string": "a", "new_string": "b"}
            )
        ],
    )
    code = _run_main(monkeypatch, tmp_path, _payload_with(transcript))
    out = capsys.readouterr().out
    assert code == 0
    assert '"decision": "block"' in out
    assert "2026-06-22-own" in out


def test_main_unreadable_transcript_falls_back_to_repo_wide_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A missing transcript must not silently disarm the gate: legacy selection applies."""
    _make_plan(tmp_path, "2026-06-22-open", _TASK_OPEN)
    code = _run_main(monkeypatch, tmp_path, _payload_with(tmp_path / "missing.jsonl"))
    out = capsys.readouterr().out
    assert code == 0
    assert '"decision": "block"' in out


# --- stop notifier hand-off (project 2026-10-10-agent-stop-email-notify) -------------------
#
# Allowed and released stops are handed to ``agent_notify.on_stop``; blocked stops,
# diagnostic runs and fail-open payloads are not session stops and never notify. The
# hand-off is fail-open: a notifier that raises or cannot be imported changes nothing
# the gate prints, returns or stores, and leaves one ``notify_error`` gate-log line.

_TASK_RELEASED = _TASK_OPEN.replace(
    'stop_gate: "armed"\n', 'stop_gate: "released:human-gate"\n'
)


class _OnStopRecorder:
    """Stands in for ``agent_notify.on_stop``; records each call, optionally raises."""

    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self.error = error

    def __call__(
        self,
        payload: object,
        decision: str,
        reason: str,
        kind: str,
        open_rows: int | None,
        task_file: str | None,
        release_reason: str | None = None,
    ) -> None:
        self.calls.append(
            {
                "payload": payload,
                "decision": decision,
                "reason": reason,
                "kind": kind,
                "open_rows": open_rows,
                "task_file": task_file,
                "release_reason": release_reason,
            }
        )
        if self.error is not None:
            raise self.error


def _fake_notifier(
    monkeypatch: pytest.MonkeyPatch, error: Exception | None = None
) -> _OnStopRecorder:
    """Place a fake ``agent_notify`` in ``sys.modules`` so the gate's lazy import gets it."""
    recorder = _OnStopRecorder(error)
    fake = types.ModuleType("agent_notify")
    setattr(fake, "on_stop", recorder)
    monkeypatch.setitem(sys.modules, "agent_notify", fake)
    return recorder


def test_evaluate_detail_kinds_and_evaluate_prefix(tmp_path: Path) -> None:
    """AC-B.1: ``evaluate_detail`` returns the kind, open-row count and task file; ``evaluate`` is its prefix."""
    detail = stop_gate.evaluate_detail
    done, reason, kind, open_rows, task_file = detail(tmp_path)
    assert (done, kind, open_rows, task_file) == (True, "no_active_plan", 0, None)
    assert stop_gate.evaluate(tmp_path) == (done, reason)

    task = _make_plan(tmp_path, "2026-06-22-open", _TASK_OPEN)
    done, reason, kind, open_rows, task_file = detail(tmp_path)
    assert (done, kind, open_rows) == (False, "open_rows", 2)
    assert task_file == task.as_posix()
    assert stop_gate.evaluate(tmp_path) == (done, reason)

    _make_plan(tmp_path, "2026-06-22-open", _TASK_RELEASED)
    done, reason, kind, open_rows, task_file = detail(tmp_path)
    assert (done, kind, task_file) == (True, "released", task.as_posix())
    assert stop_gate.evaluate(tmp_path) == (done, reason)

    _make_plan(tmp_path, "2026-06-22-open", _TASK_DONE)
    done, reason, kind, open_rows, task_file = detail(tmp_path)
    assert (done, kind, open_rows, task_file) == (
        True,
        "rows_complete",
        0,
        task.as_posix(),
    )
    assert stop_gate.evaluate(tmp_path) == (done, reason)


def test_main_allow_hands_stop_to_notifier_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-B.1: an allow calls ``on_stop`` once with ``decision="allow"`` and the ``evaluate_detail`` fields."""
    recorder = _fake_notifier(monkeypatch)
    _make_plan(tmp_path, "2026-06-22-done", _TASK_DONE)
    assert _run_main(monkeypatch, tmp_path, _STOP_PAYLOAD) == 0
    assert capsys.readouterr().out == ""
    assert len(recorder.calls) == 1
    call = recorder.calls[0]
    _, reason, kind, open_rows, task_file = stop_gate.evaluate_detail(tmp_path)
    assert call["decision"] == "allow"
    assert (call["reason"], call["kind"], call["open_rows"], call["task_file"]) == (
        reason,
        kind,
        open_rows,
        task_file,
    )
    assert call["kind"] == "rows_complete"
    assert call["release_reason"] is None
    payload = call["payload"]
    assert isinstance(payload, dict)
    assert payload["session_id"] == "sess-1"


def test_main_released_plan_passes_release_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-B.1: a ``released:<reason>`` stop passes the parsed reason, never the reason sentence."""
    recorder = _fake_notifier(monkeypatch)
    _make_plan(tmp_path, "2026-06-22-released", _TASK_RELEASED)
    assert _run_main(monkeypatch, tmp_path, _STOP_PAYLOAD) == 0
    assert capsys.readouterr().out == ""
    assert len(recorder.calls) == 1
    call = recorder.calls[0]
    assert (call["decision"], call["kind"], call["release_reason"]) == (
        "allow",
        "released",
        "human-gate",
    )


@pytest.mark.parametrize(
    "stdin_text",
    [
        "",
        "not json",
        "[]",
        '{"session_id": "sess-1", "hook_event_name": "SubagentStop"}',
        '{"hook_event_name": "Stop"}',
    ],
    ids=["diagnostic", "not-json", "not-object", "not-stop-event", "no-session"],
)
def test_main_non_stop_input_never_notifies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    stdin_text: str,
) -> None:
    """AC-B.2: diagnostic mode and every fail-open payload never call the notifier."""
    recorder = _fake_notifier(monkeypatch)
    _make_plan(tmp_path, "2026-06-22-done", _TASK_DONE)
    assert _run_main(monkeypatch, tmp_path, stdin_text) == 0
    capsys.readouterr()
    assert recorder.calls == []


def test_main_block_never_notifies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-B.2: a block decision is not a stop; the notifier is not called."""
    recorder = _fake_notifier(monkeypatch)
    _make_plan(tmp_path, "2026-06-22-open", _TASK_OPEN)
    for _ in range(stop_gate.MAX_CONSECUTIVE_BLOCKS):
        assert _run_main(monkeypatch, tmp_path, _STOP_PAYLOAD) == 0
        assert '"decision": "block"' in capsys.readouterr().out
    assert recorder.calls == []


def test_main_release_notifies_once_as_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-B.3: the loop-breaker release calls the notifier once with ``decision="release"`` (class blocked)."""
    recorder = _fake_notifier(monkeypatch)
    _make_plan(tmp_path, "2026-06-22-open", _TASK_OPEN)
    for _ in range(stop_gate.MAX_CONSECUTIVE_BLOCKS + 1):
        assert _run_main(monkeypatch, tmp_path, _STOP_PAYLOAD) == 0
    capsys.readouterr()
    assert len(recorder.calls) == 1
    call = recorder.calls[0]
    assert (call["decision"], call["kind"], call["open_rows"]) == (
        "release",
        "open_rows",
        2,
    )
    notifier = importlib.import_module("tools.agent_notify")
    gate = {
        "decision": call["decision"],
        "kind": call["kind"],
        "release_reason": call["release_reason"],
    }
    assert notifier.classify("Stop", call["payload"], gate) == "blocked"


def _gate_run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    root: Path,
    body: str,
    runs: int,
) -> tuple[list[int], list[str], dict[str, str], list[dict[str, object]]]:
    """Run ``main`` ``runs`` times on one plan; return exit codes, stdout, counters and log lines.

    The block reason names the task file, so stdout has the run's root replaced by
    ``<root>`` to compare two runs made under different roots.
    """
    root.mkdir(parents=True, exist_ok=True)
    log = root / "hooks.jsonl"
    monkeypatch.setenv("{{PROJECT_NAME_UPPER}}_HOOK_LOG", str(log))
    _make_plan(root, "2026-06-22-plan", body)
    codes: list[int] = []
    outs: list[str] = []
    for _ in range(runs):
        codes.append(_run_main(monkeypatch, root, _STOP_PAYLOAD))
        outs.append(capsys.readouterr().out.replace(root.as_posix(), "<root>"))
    counters = {p.name: p.read_text(encoding="utf-8") for p in _counter_files(root)}
    lines = _log_lines(log) if log.exists() else []
    return codes, outs, counters, lines


@pytest.mark.parametrize("failure", ["raises", "import-fails"])
@pytest.mark.parametrize(
    ("body", "runs"),
    [(_TASK_DONE, 1), (_TASK_OPEN, stop_gate.MAX_CONSECUTIVE_BLOCKS + 1)],
    ids=["allow", "release"],
)
def test_notifier_failure_changes_nothing_but_the_log(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: str,
    body: str,
    runs: int,
) -> None:
    """AC-B.4: a raising or unimportable notifier leaves stdout, exit code and counters identical, plus one ``notify_error`` line."""
    _fake_notifier(monkeypatch)
    base = _gate_run(monkeypatch, capsys, tmp_path / "base", body, runs)

    if failure == "raises":
        _fake_notifier(monkeypatch, RuntimeError("smtp down"))
    else:
        monkeypatch.setitem(sys.modules, "agent_notify", None)
    broken = _gate_run(monkeypatch, capsys, tmp_path / "broken", body, runs)

    assert broken[0] == base[0]
    assert broken[1] == base[1]
    assert broken[2] == base[2]
    errors = [line for line in broken[3] if "notify_error" in line.values()]
    assert len(errors) == 1
    assert [line for line in broken[3] if line not in errors] == base[3]
    assert not any("notify_error" in line.values() for line in base[3])


def test_session_notify_off_keeps_inprocess_runs_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-B.8: the test session sets ``AGENT_NOTIFY=off``, so an in-process allow writes nothing under an enabled home."""
    assert os.environ.get("AGENT_NOTIFY") == "off"
    placeholder = "@".join(("someone", "example.invalid"))
    home = tmp_path / "home"
    home.mkdir()
    (home / "notify.json").write_text(
        json.dumps(
            {
                "version": 1,
                "enabled": True,
                "dry_run": True,
                "to": [placeholder],
                "from": placeholder,
                "smtp": {"user": placeholder},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENT_NOTIFY_HOME", str(home))
    # Let the gate load the real notifier; the two calls restore sys.modules afterwards.
    monkeypatch.setitem(sys.modules, "agent_notify", types.ModuleType("agent_notify"))
    monkeypatch.delitem(sys.modules, "agent_notify")
    repo = tmp_path / "repo"
    repo.mkdir()
    assert _run_main(monkeypatch, repo, _STOP_PAYLOAD) == 0
    assert capsys.readouterr().out == ""
    assert sorted(p.name for p in home.iterdir()) == ["notify.json"]
