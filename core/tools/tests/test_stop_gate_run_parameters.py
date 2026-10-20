"""B-4: the stop gate for run-parameters plans (AC-D.1, AC-D.2, AC-D.5).

Plan: the run-parameters design plan (B-4; report R§4.6 "``stop_gate.py``
changes", D-9, D-16). Vectors V4-002, V4-003, V4-004, V4-019 and V4-020.

The gate first discovers the plan it stops on from the two binding copies (the task.md
``bound_sessions`` list and the store's ``sessions/<session>.json``), then evaluates it. For a
plan that carries a ``run_parameters`` grant, every acceptance branch (``released:done``, the
former ``rows_complete`` and ``no_active_task`` for a bound session) runs the DONE predicate
``stop_gate.plan_done(repo_root, plan) -> (done, reasons)``. Legacy plans keep today's rules;
``tools/tests/test_stop_gate.py`` and ``tools/tests/test_stop_gate_done.py`` stay byte-unchanged.

Each test imports ``tools.stop_gate`` in its body, so a missing name fails the test rather
than the collection. The tests drive ``main()`` with a Stop payload whose ``session_id`` is the
fixture session, inside the fixture environment.
"""

from __future__ import annotations

import importlib
import io
import itertools
import json
import shutil
import sys
import uuid
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

from tools.tests.run_parameters_fixtures import build_fixture as bf

ROOT = Path(__file__).resolve().parents[2]
ROWS_DONE = {"1": "[x]", "H2-6": "[x]"}
ROWS_OPEN = {"1": "[x]", "H2-6": "[ ]"}
B_BLOCK = (
    "\n### B-2\n\n"
    "Decision: the human holds the live check "
    "([decision](../../../../.agent/context/handoffs/fixture-decision.md)).\n"
)


def _sg() -> ModuleType:
    return importlib.import_module("tools.stop_gate")


def _build(tmp_path: Path, name: str = "fx") -> bf.Fixture:
    """A built fixture; ``PLAN_B`` stays armed with an open row, and every test rewrites
    ``fx.plan`` after it, so today's mtime selection picks ``fx.plan``."""
    return bf.build(tmp_path / name, ROOT)


def _bound(tmp_path: Path) -> bf.Fixture:
    """A fixture whose plan is initialized and bound to the fixture session (both copies)."""
    fx = _build(tmp_path)
    code, out = fx.run("init", "--plan", fx.plan)
    assert (code, out.get("result")) == (0, "initialized"), out
    for flag in ("--pending", "--plan"):
        code, out = fx.run("bind", flag, fx.plan, "--session", fx.session)
        assert code == 0, out
    return fx


def _split(path: Path) -> tuple[dict[str, Any], str]:
    head, body = path.read_text(encoding="utf-8").split("---\n", 2)[1:]
    return yaml.safe_load(head), body


def _rewrite(
    path: Path,
    rows: dict[str, str] | None,
    tail: str,
    labels: dict[str, str] | None = None,
    **keys: Any,
) -> None:
    data, body = _split(path)
    for key, value in keys.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    if rows is not None:
        names = labels or {}
        body = (
            "\n# Task\n\n| # | Task | Status |\n| :- | :- | :- |\n"
            + "".join(
                f"| {row} | {names.get(row, 'fixture row')} | {mark} |\n"
                for row, mark in rows.items()
            )
            + tail
        )
    path.write_bytes((bf.frontmatter(data) + body).encode("utf-8"))


def _task(
    fx: bf.Fixture,
    plan: str | None = None,
    *,
    rows: dict[str, str] | None = None,
    tail: str = "",
    labels: dict[str, str] | None = None,
    **keys: Any,
) -> None:
    """Rewrite task.md frontmatter keys (``None`` deletes one) and, with ``rows``, its table."""
    _rewrite(fx.task_path(plan), rows, tail, labels, **keys)


def _plan(fx: bf.Fixture, plan: str | None = None, **keys: Any) -> None:
    """Rewrite implementation-plan.md frontmatter keys (``None`` deletes one)."""
    _rewrite(fx.plan_path(plan), None, "", **keys)


def _stop(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    repo: Path,
    session: str,
    env: dict[str, str],
    receipts: Path | None = None,
) -> tuple[bool, str]:
    """Run the Stop hook once; return ``(allowed, reason)``."""
    payload = json.dumps(
        {"session_id": session, "hook_event_name": "Stop", "stop_hook_active": False}
    )
    run_env = {
        **env,
        "{{PROJECT_NAME_UPPER}}_RECEIPTS": str(receipts or tmp_path / "receipts" / uuid.uuid4().hex),
        "{{PROJECT_NAME_UPPER}}_HOOK_LOG": str(tmp_path / "hook.jsonl"),
        "AGENT_NOTIFY": "off",
    }
    capsys.readouterr()
    module = _sg()
    saved = sys.stdin
    with bf.patched_environ(run_env):
        sys.stdin = io.StringIO(payload)
        try:
            code = module.main([str(repo)])
        finally:
            sys.stdin = saved
    assert code == 0
    captured = capsys.readouterr()
    if not captured.out.strip():
        return True, captured.err
    verdict = json.loads(captured.out)
    assert verdict["decision"] == "block", verdict
    return False, str(verdict["reason"])


def _fx_stop(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    fx: bf.Fixture,
    session: str | None = None,
) -> tuple[bool, str]:
    return _stop(tmp_path, capsys, fx.repo, session or fx.session, fx.env())


def _done(
    monkeypatch: pytest.MonkeyPatch, value: bool, calls: list[str] | None = None
) -> None:
    """Replace the DONE predicate; record the plans it is asked about."""

    def plan_done(repo_root: Path, plan: str) -> tuple[bool, list[str]]:
        if calls is not None:
            calls.append(plan)
        return value, [] if value else ["fixture_not_done"]

    monkeypatch.setattr(_sg(), "plan_done", plan_done)


# -- V4-002: the acceptance branches -------------------------------------------------------


def test_vec_v4_002_every_acceptance_branch_runs_the_done_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-D.1: ``released:done``, all rows ``[x]`` and a bound ``complete`` plan are blocked
    while the DONE predicate fails (no final receipt); the block names ``not_done`` or
    ``no_active_task``."""
    fx = _bound(tmp_path)
    _task(fx, rows=ROWS_DONE, stop_gate="released:done")
    allowed, reason = _fx_stop(tmp_path, capsys, fx)
    assert not allowed and "not_done" in reason, reason
    _task(fx, stop_gate="armed")
    allowed, reason = _fx_stop(tmp_path, capsys, fx)
    assert not allowed and "not_done" in reason, reason
    _task(fx, status="complete", stop_gate="released:done")
    _plan(fx, status="complete")
    allowed, reason = _fx_stop(tmp_path, capsys, fx)
    assert not allowed and "no_active_task" in reason, reason


def test_vec_v4_002_done_predicate_releases_each_branch(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-D.1: when ``plan_done`` holds, each of the three branches allows the stop."""
    fx = _bound(tmp_path)
    calls: list[str] = []
    _done(monkeypatch, True, calls)
    _task(fx, rows=ROWS_DONE, stop_gate="released:done")
    assert _fx_stop(tmp_path, capsys, fx)[0]
    _task(fx, stop_gate="armed")
    assert _fx_stop(tmp_path, capsys, fx)[0]
    _task(fx, status="complete", stop_gate="released:done")
    _plan(fx, status="complete")
    assert _fx_stop(tmp_path, capsys, fx)[0]
    assert calls == [fx.plan, fx.plan, fx.plan]


def test_vec_v4_002_other_release_reasons_stay_sanctioned(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-D.1: ``released:human-gate`` on a grant plan with open rows is a non-DONE stop
    that needs no DONE check."""
    fx = _bound(tmp_path)
    calls: list[str] = []
    _done(monkeypatch, False, calls)
    _task(fx, rows=ROWS_OPEN, stop_gate="released:human-gate")
    allowed, reason = _fx_stop(tmp_path, capsys, fx)
    assert allowed, reason
    assert calls == []


def test_vec_v4_002_blocked_row_needs_its_evidence(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-D.1: on a grant plan a ``[B]`` row counts as closed only with its ``### B-<row>``
    block; without it the row is open even when ``plan_done`` holds."""
    fx = _bound(tmp_path)
    _done(monkeypatch, True)
    rows = {"1": "[x]", "2": "[B]"}
    labels = {"2": "Live check, follow-up in B-2"}
    _task(fx, rows=rows, labels=labels, stop_gate="armed")
    allowed, reason = _fx_stop(tmp_path, capsys, fx)
    assert not allowed and "B-2" in reason, reason
    _task(fx, rows=rows, labels=labels, tail=B_BLOCK, stop_gate="armed")
    allowed, reason = _fx_stop(tmp_path, capsys, fx)
    assert allowed, reason


def test_vec_v4_002_grant_plan_without_receipt_blocked_legacy_allowed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-D.2: a ``run-parameters/1`` plan with ``released:done`` and no final receipt is
    blocked (an unbound session: today's selection, then the DONE check); the same
    frontmatter with no block is allowed by today's rules."""
    fx = _build(tmp_path)
    _task(fx, rows=ROWS_DONE, stop_gate="released:done")
    allowed, reason = _fx_stop(tmp_path, capsys, fx, session=str(uuid.uuid4()))
    assert not allowed and "not_done" in reason, reason
    legacy = tmp_path / "legacy"
    task = legacy / "docs" / "execution" / "plans" / bf.PLAN / "task.md"
    task.parent.mkdir(parents=True)
    shutil.copyfile(fx.task_path(), task)
    _rewrite(task, None, "", run_parameters=None, bound_sessions=None)
    allowed, reason = _stop(tmp_path, capsys, legacy, str(uuid.uuid4()), bf.git_env())
    assert allowed, reason
    assert "released:done" in reason


def test_vec_v4_002_upper_case_done_stays_blocked(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-D.5: an ``in_progress`` grant plan with ``released:DONE`` is not released: the
    value is outside ``RELEASE_REASONS``, so the bound plan stays gated."""
    fx = _bound(tmp_path)
    _done(monkeypatch, False)
    _task(fx, rows=ROWS_OPEN, stop_gate="released:DONE")
    allowed, reason = _fx_stop(tmp_path, capsys, fx)
    assert not allowed, reason
    _task(fx, rows=ROWS_DONE, stop_gate="released:DONE")
    allowed, reason = _fx_stop(tmp_path, capsys, fx)
    assert not allowed, reason


# -- V4-003 / V4-004: discovery by both binding copies -------------------------------------


def test_vec_v4_003_bound_plan_wins_over_a_newer_armed_plan(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-D.1: tree copy and store copy agree → that plan, whatever the mtime selection
    would choose; ``discover`` reports ``bound``."""
    fx = _bound(tmp_path)
    _task(fx, rows=ROWS_OPEN, stop_gate="armed")
    other = "2026-10-18-newer-plan"
    task = fx.plan_dir(other) / "task.md"
    task.parent.mkdir(parents=True)
    task.write_bytes(
        (
            bf.frontmatter({"status": "in_progress", "stop_gate": "armed"})
            + "\n| # | Task | Status |\n| :- | :- | :- |\n| 9 | newer row | [ ] |\n"
        ).encode("utf-8")
    )
    allowed, reason = _fx_stop(tmp_path, capsys, fx)
    assert not allowed
    assert fx.plan in reason and other not in reason, reason
    with bf.patched_environ(fx.env()):
        assert _sg().discover(fx.repo, fx.session) == ("bound", fx.plan)


def test_vec_v4_003_unbound_and_pending_sessions_use_todays_selection(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-D.1: none/none and none/pending → today's selection; the pending plan is named."""
    fx = _build(tmp_path)
    code, out = fx.run("init", "--plan", fx.plan)
    assert code == 0, out
    _task(fx, rows=ROWS_OPEN, stop_gate="released:human-gate")
    stranger = str(uuid.uuid4())
    with bf.patched_environ(fx.env()):
        assert _sg().discover(fx.repo, stranger) == ("today", None)
    assert _fx_stop(tmp_path, capsys, fx, session=stranger)[0]
    code, out = fx.run("bind", "--pending", fx.plan, "--session", fx.session)
    assert code == 0, out
    with bf.patched_environ(fx.env()):
        assert _sg().discover(fx.repo, fx.session) == ("pending", fx.plan)
    allowed, reason = _fx_stop(tmp_path, capsys, fx)
    assert allowed, reason


def _drop_tree_copy(fx: bf.Fixture) -> None:
    _task(fx, bound_sessions=[])


def _mismatch(fx: bf.Fixture) -> None:
    other = "2026-10-18-other-plan"
    fx.plan_dir(other).mkdir(parents=True)
    shutil.copyfile(fx.task_path(), fx.task_path(other))
    _drop_tree_copy(fx)


def _two_plans(fx: bf.Fixture) -> None:
    other = "2026-10-18-other-plan"
    fx.plan_dir(other).mkdir(parents=True)
    shutil.copyfile(fx.task_path(), fx.task_path(other))


def _drop_store_record(fx: bf.Fixture) -> None:
    (fx.store / "sessions" / f"{fx.session}.json").unlink()


def _drop_store(fx: bf.Fixture) -> None:
    shutil.rmtree(fx.store)


def _corrupt_store_record(fx: bf.Fixture) -> None:
    (fx.store / "sessions" / f"{fx.session}.json").write_bytes(b"{")


def _remove_block(fx: bf.Fixture) -> None:
    _task(fx, run_parameters=None)
    _plan(fx, run_parameters=None)


def _manual(fx: bf.Fixture) -> None:
    block = dict(fx.block, authorization={"schema": "manual"})
    _task(fx, run_parameters=block)
    _plan(fx, run_parameters=block)


DISAGREEMENTS = {
    "tree_binding_missing": _drop_tree_copy,
    "binding_mismatch": _mismatch,
    "ambiguous_binding": _two_plans,
    "binding_lost": _drop_store_record,
    "store_missing": _drop_store,
    "store_unavailable": _corrupt_store_record,
    "binding_removed": _remove_block,
    "manual_downgrade": _manual,
}


@pytest.mark.parametrize("outcome", sorted(DISAGREEMENTS))
def test_vec_v4_004_disagreements_block_with_their_outcome(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], outcome: str
) -> None:
    """AC-D.1: every disagreement row of the discovery table blocks and names its outcome,
    even when today's rules would allow the stop (``released:human-gate``)."""
    fx = _bound(tmp_path)
    _task(fx, rows=ROWS_OPEN, stop_gate="released:human-gate")
    DISAGREEMENTS[outcome](fx)
    allowed, reason = _fx_stop(tmp_path, capsys, fx)
    assert not allowed, reason
    assert outcome in reason, reason


def test_vec_v4_004_manual_after_verified_revoke_follows_todays_rules(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-D.1: a grant-bound plan becomes manual only through a verified ``revoke``; then
    today's rules apply (a sanctioned release allows the stop)."""
    fx = _bound(tmp_path)
    _task(fx, rows=ROWS_OPEN, stop_gate="released:human-gate")
    session = str(uuid.uuid4())
    uid = str(fx.block["authorization"]["message_uuid"])
    record = fx.add_human(f"revoke run_parameters {uid}", parent=None, session=session)
    code, out = fx.run("revoke", "--session", session, "--message", record)
    assert (code, out.get("result")) == (0, "revoked"), out
    _manual(fx)
    allowed, reason = _fx_stop(tmp_path, capsys, fx)
    assert allowed, reason


def test_vec_v4_004_second_plan_in_one_session_is_refused(tmp_path: Path) -> None:
    """AC-D.1: two open plans in one session are impossible by construction."""
    fx = _bound(tmp_path)
    other = "2026-10-18-other-plan"
    fx.plan_dir(other).mkdir(parents=True)
    shutil.copyfile(fx.task_path(), fx.task_path(other))
    code, out = fx.run("bind", "--pending", other, "--session", fx.session)
    assert (code, out.get("reason")) == (1, "session_busy"), out


def test_vec_v4_004_handed_over_session_is_blocked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-D.1: after ``bind --plan`` in a new session the old session's entry is
    ``handed_over``; the old session's stop names it; the new session is the bound one."""
    fx = _bound(tmp_path)
    _task(fx, rows=ROWS_OPEN, stop_gate="released:human-gate")
    second = str(uuid.uuid4())
    fx.add_system(parent=None, session=second)
    code, out = fx.run("bind", "--plan", fx.plan, "--session", second)
    assert code == 0, out
    allowed, reason = _fx_stop(tmp_path, capsys, fx)
    assert not allowed and "handed_over" in reason, reason
    with bf.patched_environ(fx.env()):
        assert _sg().discover(fx.repo, second) == ("bound", fx.plan)
    assert _fx_stop(tmp_path, capsys, fx, session=second)[0]


# -- V4-019: the loop-breaker ----------------------------------------------------------------


def test_vec_v4_019_loop_breaker_is_an_emergency_release(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-D.1: after ``MAX_CONSECUTIVE_BLOCKS`` blocks the gate fails open, classified and
    logged as ``emergency_release`` (a non-DONE stop)."""
    fx = _bound(tmp_path)
    _task(fx, rows=ROWS_OPEN, stop_gate="armed")
    receipts = tmp_path / "loop-receipts"
    limit = _sg().MAX_CONSECUTIVE_BLOCKS
    for _ in range(limit):
        allowed, _ = _stop(tmp_path, capsys, fx.repo, fx.session, fx.env(), receipts)
        assert not allowed
    allowed, err = _stop(tmp_path, capsys, fx.repo, fx.session, fx.env(), receipts)
    assert allowed
    assert "emergency" in err, err
    lines = (tmp_path / "hook.jsonl").read_text(encoding="utf-8").splitlines()
    last = json.loads(lines[-1])
    assert last["decision"] == "emergency_release", last
    assert last["plan"] == fx.plan, last


# -- V4-020: the transition table ------------------------------------------------------------


def _expected(grant: bool, released: bool, open_rows: bool, done: bool) -> bool:
    """Legacy: today's rules. Grant: ``released:done`` follows the DONE predicate alone
    (``status --plan`` already requires no open row); ``armed`` needs no open row and DONE."""
    if not grant:
        return released or not open_rows
    if released:
        return done
    return done and not open_rows


def test_vec_v4_020_every_boolean_combination(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-D.1: grant × ``released:done`` × open rows × DONE × bound, against the table."""
    fx = _bound(tmp_path)
    legacy = tmp_path / "legacy"
    legacy_task = legacy / "docs" / "execution" / "plans" / bf.PLAN / "task.md"
    legacy_task.parent.mkdir(parents=True)
    shutil.copyfile(fx.task_path(), legacy_task)
    _rewrite(legacy_task, None, "", run_parameters=None, bound_sessions=None)
    stranger = str(uuid.uuid4())
    seen: list[tuple[bool, ...]] = []
    for grant, released, open_rows, done, bound in itertools.product(
        (True, False), repeat=5
    ):
        if not grant and bound:
            continue
        calls: list[str] = []
        _done(monkeypatch, done, calls)
        rows = ROWS_OPEN if open_rows else ROWS_DONE
        gate = "released:done" if released else "armed"
        if grant:
            _task(fx, rows=rows, stop_gate=gate)
            session = fx.session if bound else stranger
            allowed, reason = _stop(tmp_path, capsys, fx.repo, session, fx.env())
        else:
            _rewrite(legacy_task, rows, "", stop_gate=gate)
            allowed, reason = _stop(
                tmp_path, capsys, legacy, str(uuid.uuid4()), bf.git_env()
            )
            assert calls == [], "a legacy plan never runs the DONE predicate"
        case = (grant, released, open_rows, done, bound)
        assert allowed is _expected(grant, released, open_rows, done), (case, reason)
        seen.append(case)
    assert len(seen) == 24
