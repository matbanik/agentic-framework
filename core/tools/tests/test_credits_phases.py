"""B-6 tests for the phase machine of R§4.4 (WP-7; AC-F.1 to AC-F.5).

Every ``V6-`` vector of the design plan's ``vectors.yaml`` except the live V6-053 has a test whose name
holds ``vec_v6_<nnn>_``: here, or in an ``It`` appended to ``tools/tests/Start-CreditsRun.Tests.ps1``
(V6-047) or ``tools/tests/Watch-CreditsRuns.Tests.ps1`` (V6-022, V6-027, V6-049, V6-050). V6-053
is the B6-RUN receipt (row 16).

The tests fix this contract (EA-19, EA-20):

* ``tools/run_parameters.py`` holds the engine. The pure step
  ``phase_step(last, event, payload, facts)`` takes the last transition record (``None`` before
  the first one) and returns the outcome: ``event``, ``to``, ``guard_result`` and, for a
  ``STOPPED:*`` or ``PARKED:*`` successor, ``suspended`` and ``pending_op`` (and ``parked_by``).
  A stay or an ``ignored`` pair has ``to == from``. A fact that is missing is false.
* ``record_transition(repo, *, plan, run_id, event, payload, by, facts=None, from_seq=None,
  op_id="none")`` evaluates and appends one record under ``store.lock`` and returns it. The
  engine owns ``verdict_ok``, ``row_closed``, ``e17_recorded``, ``pending_op``, ``commit_plan``,
  ``exec_after_plan``, ``authority_ok`` and ``fork_verified``; every other guard fact comes from
  the caller.
* ``phase_state`` is ``{"state", "seq"}`` of the last record whose ``to`` differs from its
  ``from`` (``plan:active`` and ``0`` before one), and ``ops/<plan>/<run>/state.json`` is its view.
* ``tools/credits_state.py`` keeps the derived view (``phase_sync``, ``phase_status``) and reads
  the manifest ``phases`` key; ``tools/credits_msg.py`` holds the phase-aware resume check.

Every fixture is built inside the test body (``bf.build``) and every module is imported inside it,
so a missing component fails the test at Red instead of erroring the collection. Crash injection
runs only in a child process.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import socket
import subprocess
import sys
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import jsonschema
import pytest
import yaml

from tools.tests.run_parameters_fixtures import build_fixture as bf

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / bf.RUN_PARAMETERS_HOME / "schemas"
STATE_TOOL = ROOT / "tools" / "credits_state.py"
RESUME_BRIEF = (
    ROOT / ".agent" / "skills" / "claude-credits" / "templates" / "resume-brief.md"
)
CREDITS_SCHEMA = (
    ROOT / ".agent" / "skills" / "claude-credits" / "schemas" / "credits-run.v1.json"
)
CRASH = "RUN_PARAMETERS_TEST_CRASH_AT"
CLOCK = "RUN_PARAMETERS_TEST_CLOCK"
CRASH_EXIT = 97
PHASE_CRASH_POINT = "phase_record"
FAIL_CLOSED = {
    "decisions": "human-all",
    "commit_plan": False,
    "exec_after_plan": False,
    "commit_exec": False,
    "push": "never",
}
RUN = "run-fixture-1"
FORK = f"{bf.PLAN}-fork-1"
FORK_RUN = "run-fixture-fork-1"
START = "C:/Temp/fixture/start-record.json"
VERDICT = f".agent/context/handoffs/{bf.PLAN}-plan-critical-review.md"
NONTERMINALS = (
    "plan:active",
    "plan:approved",
    "plan:pc_done",
    "transition:prepared",
    "transition:admitted",
    "exec:active",
    "exec:finalizing",
)
CRASH_RECOVERY = {
    "plan:active": "reenter_loop",
    "plan:approved": "recover_pending_op",
    "plan:pc_done": "reevaluate_tau2_tau3",
    "transition:prepared": "rerun_tau3_admit",
    "transition:admitted": "rerun_tau4",
    "exec:active": "resume_row",
    "exec:finalizing": "recover_pending_op",
}
RESUME_GROUPS = {
    "plan:active": {"i": "n/a", "ii": "n/a", "iii": "retained", "iv": "retained"},
    "plan:approved": {"i": "n/a", "ii": "n/a", "iii": "replaced", "iv": "retained"},
    "plan:pc_done": {"i": "n/a", "ii": "n/a", "iii": "retained", "iv": "retained"},
    "transition:prepared": {
        "i": "n/a",
        "ii": "n/a",
        "iii": "retained",
        "iv": "retained",
    },
    "transition:admitted": {
        "i": "replaced",
        "ii": "retained",
        "iii": "retained",
        "iv": "retained",
    },
    "exec:active": {
        "i": "retained",
        "ii": "replaced",
        "iii": "retained",
        "iv": "retained",
    },
    "exec:finalizing": {
        "i": "replaced",
        "ii": "replaced",
        "iii": "retained",
        "iv": "retained",
    },
}
RESUME_OK = {
    "base_ok": True,
    "commit_grant_unset": True,
    "start_ref_ok": True,
    "reservation_present": True,
    "binding_active": True,
    "worktree_present": True,
    "worktree_ok": True,
    "removal_recorded": False,
    "active_tree_ok": True,
    "acts_unconsumed": True,
}
PC_FACTS = {"pc_reserved": True, "pc_reconciled": True, "ref_matches": True}
PREPARE_FACTS = {"exec_start_reserved": True, "base_matches": True}
ADMIT_FACTS = {"lease": True, "path_free": True, "binding_active": True}

Result = tuple[int, dict[str, Any]]


# -- helpers -------------------------------------------------------------------------------


def _rp() -> ModuleType:
    """The engine module, imported inside a test body (a Red import error is a failure)."""
    return importlib.import_module("tools.run_parameters")


def _cs() -> ModuleType:
    return importlib.import_module("tools.credits_state")


def _msg() -> ModuleType:
    """``credits_msg`` imports its sibling as ``credits_state``, as when it runs as a script."""
    tools = str(ROOT / "tools")
    if tools not in sys.path:
        sys.path.append(tools)
    return importlib.import_module("credits_msg")


def _build(tmp_path: Path, name: str = "fx", **kw: Any) -> bf.Fixture:
    return bf.build(tmp_path / name, ROOT, **kw)


def _init(fx: bf.Fixture, *, plan: str | None = None) -> dict[str, Any]:
    code, out = fx.run("init", "--plan", plan or fx.plan)
    assert (code, out.get("result")) == (0, "initialized"), out
    return out


def _verify(fx: bf.Fixture, act: str, *, plan: str | None = None) -> Result:
    return fx.run("verify", act, "--plan", plan or fx.plan)


def _reserve(fx: bf.Fixture, act: str, op: str, *, plan: str | None = None) -> Result:
    return fx.run("reserve", act, "--plan", plan or fx.plan, "--op", op)


def _refused(res: Result, reason: str, *, effective: bool = True) -> None:
    code, out = res
    assert out.get("reason") == reason, out
    assert code == 1, out
    assert out.get("result") == "refused", out
    assert out.get("authorized") is False, out
    assert out.get("failure") is True, out
    if effective:
        assert out.get("effective") == FAIL_CLOSED, out


def _verified(res: Result) -> dict[str, Any]:
    code, out = res
    assert out.get("result") == "verified", out
    assert code == 0, out
    assert out.get("authorized") is True, out
    return out


def _schema_valid(name: str, root: str, instance: object) -> None:
    schema = json.loads(
        (SCHEMAS / f"{name}.v1.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator(schema).validate({root: instance})


def _frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), path
    data = yaml.safe_load(text.split("---\n", 2)[1])
    assert isinstance(data, dict), path
    return data


def _mu(block: Mapping[str, Any]) -> str:
    return str(block["authorization"]["message_uuid"])


def _corrupt_grant(fx: bf.Fixture) -> None:
    (fx.store / "grants" / f"{_mu(fx.block)}.json").write_text(
        '{"x": 1}\n', encoding="utf-8"
    )


def _stale_lock(fx: bf.Fixture) -> None:
    """A ``store.lock`` whose owner has exited (the B-2 lock body)."""
    body = {
        "pid": fx.dead_pid(),
        "pid_start": "fixture-start",
        "host": socket.gethostname(),
        "session": fx.session,
        "token": uuid.uuid4().hex,
        "ts": bf.FIXTURE_CLOCK,
    }
    _schema_valid("store", "run-parameters-store", {"lock": body})
    (fx.store / "store.lock").write_text(json.dumps(body) + "\n", encoding="utf-8")


def _session_record(fx: bf.Fixture, session: str) -> dict[str, Any]:
    record = fx.read_json(f"sessions/{session}.json")
    _schema_valid("session", "run-parameters-session", record)
    return record


def _step(
    state: str,
    event: str,
    payload: Mapping[str, Any] | None = None,
    facts: Mapping[str, Any] | None = None,
    **last: Any,
) -> dict[str, Any]:
    """One pure step from a last record whose ``to`` is ``state``."""
    record = {"to": state, **last}
    return dict(_rp().phase_step(record, event, dict(payload or {}), dict(facts or {})))


def _transitioned(res: Mapping[str, Any], to: str, event: str) -> None:
    assert (res["to"], res["guard_result"], res["event"]) == (to, "passed", event), res


def _stopped(res: Mapping[str, Any], to: str, suspended: str) -> None:
    assert res["to"] == to, res
    assert res["suspended"] == suspended, res
    assert isinstance(res["pending_op"], str), res


def _parked(res: Mapping[str, Any], parked_by: str, suspended: str) -> None:
    _stopped(res, "PARKED:approved", suspended)
    assert res["parked_by"] == parked_by, res


def _stay(res: Mapping[str, Any], state: str) -> None:
    assert res["to"] == state, res
    assert res["guard_result"] != "passed", res


def _refusal(exc: BaseException, reason: str) -> None:
    assert isinstance(exc, _rp().Refusal), exc
    assert getattr(exc, "reason", None) == reason, exc


def _record(
    fx: bf.Fixture,
    event: str,
    payload: Mapping[str, Any] | None = None,
    *,
    facts: Mapping[str, Any] | None = None,
    run_id: str = RUN,
    plan: str | None = None,
    by: str = "run",
    from_seq: int | None = None,
    op_id: str = "none",
) -> dict[str, Any]:
    """One ``record_transition`` call in-process, under the fixture environment."""
    with bf.patched_environ(fx.env()):
        record = _rp().record_transition(
            fx.repo,
            plan=plan or fx.plan,
            run_id=run_id,
            event=event,
            payload=dict(payload or {}),
            by=by,
            facts=dict(facts or {}),
            from_seq=from_seq,
            op_id=op_id,
        )
    return dict(record)


def _transitions(
    fx: bf.Fixture, *, run_id: str = RUN, plan: str | None = None
) -> list[dict[str, Any]]:
    with bf.patched_environ(fx.env()):
        records = _rp().phase_transitions(fx.repo, plan=plan or fx.plan, run_id=run_id)
    return [dict(r) for r in records]


def _state(
    fx: bf.Fixture, *, run_id: str = RUN, plan: str | None = None
) -> dict[str, Any]:
    with bf.patched_environ(fx.env()):
        return dict(_rp().phase_state(fx.repo, plan=plan or fx.plan, run_id=run_id))


def _ops_file(
    fx: bf.Fixture, name: str, *, run_id: str = RUN, plan: str | None = None
) -> Path:
    return fx.store / "ops" / (plan or fx.plan) / run_id / name


def _write_verdict(fx: bf.Fixture, plan: str | None = None) -> str:
    """The plan review's ``approved`` verdict file, target-bound to ``plan``."""
    slug = plan or fx.plan
    rel = f".agent/context/handoffs/{slug}-plan-critical-review.md"
    fx.write_text(
        rel,
        f'---\nplan: "{slug}"\nverdict: "approved"\nfindings_count: 0\n---\n\n'
        "# Plan critical review\n\nverdict: approved\n",
    )
    return rel


def _drive(fx: bf.Fixture, target: str, *, run_id: str = RUN) -> None:
    """Record the progress events that take ``run_id`` from ``plan:active`` to ``target``."""
    head = bf.git(fx.repo, "rev-parse", "HEAD")
    steps: list[tuple[str, str, dict[str, Any], dict[str, Any], str]] = [
        ("plan:approved", "E1", {"verdict_path": _write_verdict(fx)}, {}, "none"),
        (
            "plan:pc_done",
            "E3",
            {"op_id": "op-pc", "ref_new": head},
            PC_FACTS,
            "op-pc",
        ),
        ("transition:prepared", "τ3", {}, PREPARE_FACTS, "op-exec"),
        ("transition:admitted", "τ3", {}, ADMIT_FACTS, "op-exec"),
        ("exec:active", "τ4", {}, {"worktree_proven": True}, "op-exec"),
        (
            "exec:finalizing",
            "E12",
            {"receipt": "readiness.json"},
            {"readiness_ok": True},
            "none",
        ),
    ]
    if target == "plan:active":
        return
    for to, event, payload, facts, op_id in steps:
        record = _record(fx, event, payload, facts=facts, run_id=run_id, op_id=op_id)
        assert record["to"] == to, record
        if to == target:
            return
    raise AssertionError(f"unknown target state {target!r}")


def _mark_row(fx: bf.Fixture, row: str, mark: str = "[x]") -> None:
    path = fx.task_path()
    text = path.read_text(encoding="utf-8")
    old = f"| {row} | fixture row | [ ] |"
    assert old in text, text
    path.write_bytes(
        text.replace(old, f"| {row} | fixture row | {mark} |").encode("utf-8")
    )


# -- AC-F.1 the transition table (pure) ----------------------------------------------------


@pytest.mark.unit
def test_vec_v6_001_plan_active_e1_approved() -> None:
    """AC-F.1: ``plan:active`` E1 → ``plan:approved``; a failed verdict stays; a path outside handoffs is invalid."""
    rp = _rp()
    first = dict(
        rp.phase_step(None, "E1", {"verdict_path": VERDICT}, {"verdict_ok": True})
    )
    _transitioned(first, "plan:approved", "E1")
    _transitioned(
        _step("plan:active", "E1", {"verdict_path": VERDICT}, {"verdict_ok": True}),
        "plan:approved",
        "E1",
    )
    failed = _step(
        "plan:active", "E1", {"verdict_path": VERDICT}, {"verdict_ok": False}
    )
    assert (failed["to"], failed["guard_result"]) == (
        "plan:active",
        "guard_failed:verdict",
    )
    outside = _step(
        "plan:active", "E1", {"verdict_path": "docs/review.md"}, {"verdict_ok": True}
    )
    assert (outside["to"], outside["guard_result"]) == (
        "plan:active",
        "payload_invalid",
    )


@pytest.mark.unit
@pytest.mark.parametrize("cause", ["round_cap", "reviewer_unavailable"])
def test_vec_v6_002_plan_active_e2_loop_exit(cause: str) -> None:
    """AC-F.1: ``plan:active`` E2 → ``STOPPED:<cause>``; any other cause is invalid."""
    _stopped(
        _step("plan:active", "E2", {"cause": cause}), f"STOPPED:{cause}", "plan:active"
    )
    bad = _step("plan:active", "E2", {"cause": "tired"})
    assert (bad["to"], bad["guard_result"]) == ("plan:active", "payload_invalid")


@pytest.mark.unit
def test_vec_v6_003_plan_active_e5_decision() -> None:
    """AC-F.1: ``plan:active`` E5 → ``STOPPED:decision``; E5 with no code is invalid."""
    _stopped(
        _step("plan:active", "E5", {"code": "consumed"}),
        "STOPPED:decision",
        "plan:active",
    )
    bad = _step("plan:active", "E5", {})
    assert (bad["to"], bad["guard_result"]) == ("plan:active", "payload_invalid")


@pytest.mark.unit
def test_vec_v6_004_plan_approved_tau1_pc_na() -> None:
    """AC-F.1: τ1 under ``commit_plan: false`` → ``plan:pc_done``; under ``true`` the state stays."""
    _transitioned(
        _step("plan:approved", "τ1", {}, {"commit_plan": False}), "plan:pc_done", "τ1"
    )
    _stay(_step("plan:approved", "τ1", {}, {"commit_plan": True}), "plan:approved")


@pytest.mark.unit
def test_vec_v6_005_plan_approved_e3_reconciled() -> None:
    """AC-F.1: E3 → ``plan:pc_done``; a ref that disagrees → ``STOPPED:ambiguous`` with the op kept."""
    payload = {"op_id": "op-pc", "ref_new": "a" * 40}
    facts = {"commit_plan": True, **PC_FACTS}
    _transitioned(_step("plan:approved", "E3", payload, facts), "plan:pc_done", "E3")
    bad = _step("plan:approved", "E3", payload, {**facts, "ref_matches": False})
    _stopped(bad, "STOPPED:ambiguous", "plan:approved")
    assert bad["pending_op"] == "op-pc", bad


@pytest.mark.unit
def test_vec_v6_006_plan_approved_e4_pc_failed() -> None:
    """AC-F.1: E4 → ``STOPPED:decision`` with the ``PC`` op as ``pending_op``."""
    res = _step(
        "plan:approved", "E4", {"op_id": "op-pc", "phase": "commit", "reason": "hook"}
    )
    _stopped(res, "STOPPED:decision", "plan:approved")
    assert res["pending_op"] == "op-pc", res


@pytest.mark.unit
def test_vec_v6_007_authority_refusal_before_and_after_execution() -> None:
    """AC-F.1: a refusal before execution parks (``authority``); one after it stops."""
    _parked(
        _step("plan:approved", "E5", {"code": "revoked"}), "authority", "plan:approved"
    )
    _stopped(
        _step("exec:active", "E10", {"code": "revoked"}),
        "STOPPED:decision",
        "exec:active",
    )


@pytest.mark.unit
def test_vec_v6_008_plan_pc_done_tau2_park() -> None:
    """AC-F.1: τ2 under ``exec_after_plan: false`` and no E17 → parked; otherwise τ3 follows."""
    _parked(
        _step(
            "plan:pc_done", "τ2", {}, {"exec_after_plan": False, "e17_recorded": False}
        ),
        "exec_after_plan",
        "plan:pc_done",
    )
    _stay(_step("plan:pc_done", "τ2", {}, {"exec_after_plan": True}), "plan:pc_done")
    _stay(
        _step(
            "plan:pc_done", "τ2", {}, {"exec_after_plan": False, "e17_recorded": True}
        ),
        "plan:pc_done",
    )


@pytest.mark.unit
def test_vec_v6_009_plan_pc_done_tau3_prepare() -> None:
    """AC-F.1: τ3 (prepare) → ``transition:prepared``; the failing guard names the park."""
    ok = {"exec_after_plan": True, **PREPARE_FACTS}
    _transitioned(_step("plan:pc_done", "τ3", {}, ok), "transition:prepared", "τ3")
    _parked(
        _step("plan:pc_done", "τ3", {}, {**ok, "exec_start_reserved": False}),
        "authority",
        "plan:pc_done",
    )
    _parked(
        _step("plan:pc_done", "τ3", {}, {**ok, "base_matches": False}),
        "base",
        "plan:pc_done",
    )
    _parked(
        _step(
            "plan:pc_done",
            "τ3",
            {},
            {**ok, "exec_start_reserved": False, "base_matches": False},
        ),
        "authority",
        "plan:pc_done",
    )
    e17 = {"exec_after_plan": False, "e17_recorded": True, "base_matches": True}
    _transitioned(_step("plan:pc_done", "τ3", {}, e17), "transition:prepared", "τ3")


@pytest.mark.unit
def test_vec_v6_010_plan_pc_done_e5_e7_park() -> None:
    """AC-F.1: ``plan:pc_done`` E5 parks by ``authority``, E7 by ``base``."""
    _parked(
        _step("plan:pc_done", "E5", {"code": "revoked"}), "authority", "plan:pc_done"
    )
    _parked(
        _step("plan:pc_done", "E7", {"expected": "a" * 40, "found": "b" * 40}),
        "base",
        "plan:pc_done",
    )


@pytest.mark.unit
def test_vec_v6_011_transition_prepared_tau3_admit() -> None:
    """AC-F.1: τ3 (admit) → ``transition:admitted``; a failed guard parks by ``admission``."""
    _transitioned(
        _step("transition:prepared", "τ3", {}, ADMIT_FACTS), "transition:admitted", "τ3"
    )
    for key in ADMIT_FACTS:
        _parked(
            _step("transition:prepared", "τ3", {}, {**ADMIT_FACTS, key: False}),
            "admission",
            "transition:prepared",
        )


@pytest.mark.unit
def test_vec_v6_012_transition_prepared_e5_e7_e8_park() -> None:
    """AC-F.1: ``transition:prepared`` E5 / E7 / E8 → ``PARKED:approved``; a bad E8 reason is invalid."""
    for event, payload in (
        ("E5", {"code": "revoked"}),
        ("E7", {"expected": "a" * 40, "found": "b" * 40}),
        ("E8", {"reason": "path_busy"}),
    ):
        res = _step("transition:prepared", event, payload)
        _stopped(res, "PARKED:approved", "transition:prepared")
    bad = _step("transition:prepared", "E8", {"reason": "weather"})
    assert (bad["to"], bad["guard_result"]) == (
        "transition:prepared",
        "payload_invalid",
    )


@pytest.mark.unit
def test_vec_v6_013_transition_admitted_tau4() -> None:
    """AC-F.1: τ4 → ``exec:active``; an unproven worktree → ``STOPPED:ambiguous``."""
    _transitioned(
        _step("transition:admitted", "τ4", {}, {"worktree_proven": True}),
        "exec:active",
        "τ4",
    )
    _stopped(
        _step("transition:admitted", "τ4", {}, {"worktree_proven": False}),
        "STOPPED:ambiguous",
        "transition:admitted",
    )


@pytest.mark.unit
def test_vec_v6_014_transition_admitted_e8_e5_never_park() -> None:
    """AC-F.1: ``transition:admitted`` E8 → ``STOPPED:ambiguous``, E5 → ``STOPPED:decision``."""
    _stopped(
        _step("transition:admitted", "E8", {"reason": "store_refused"}),
        "STOPPED:ambiguous",
        "transition:admitted",
    )
    _stopped(
        _step("transition:admitted", "E5", {"code": "revoked"}),
        "STOPPED:decision",
        "transition:admitted",
    )


@pytest.mark.unit
def test_vec_v6_015_exec_active_e12_readiness() -> None:
    """AC-F.1: E12 with a valid readiness receipt → ``exec:finalizing``; otherwise a recorded stay."""
    payload = {"receipt": "readiness.json"}
    _transitioned(
        _step("exec:active", "E12", payload, {"readiness_ok": True}),
        "exec:finalizing",
        "E12",
    )
    _stay(_step("exec:active", "E12", payload, {"readiness_ok": False}), "exec:active")


@pytest.mark.unit
@pytest.mark.parametrize("cause", ["round_cap", "reviewer_unavailable"])
def test_vec_v6_016_exec_active_e2_loop_exit(cause: str) -> None:
    """AC-F.1: ``exec:active`` E2 → ``STOPPED:<cause>``."""
    _stopped(
        _step("exec:active", "E2", {"cause": cause}), f"STOPPED:{cause}", "exec:active"
    )


@pytest.mark.unit
@pytest.mark.parametrize("state", ["exec:active", "exec:finalizing"])
@pytest.mark.parametrize("event", ["E5", "E10"])
def test_vec_v6_017_exec_refusal_stops_with_progress(state: str, event: str) -> None:
    """AC-F.1: E5 / E10 after execution began → ``STOPPED:decision``, never a park."""
    _stopped(_step(state, event, {"code": "expired"}), "STOPPED:decision", state)
    bad = _step(state, event, {})
    assert (bad["to"], bad["guard_result"]) == (state, "payload_invalid")


@pytest.mark.unit
def test_vec_v6_018_exec_finalizing_e13_done() -> None:
    """AC-F.1: E13 with the final receipt and seal → ``DONE``; a failed guard → ``STOPPED:decision``."""
    payload = {"receipt": "final/1.json", "seal": "final/1.seal"}
    _transitioned(
        _step("exec:finalizing", "E13", payload, {"final_ok": True}), "DONE", "E13"
    )
    _stopped(
        _step("exec:finalizing", "E13", payload, {"final_ok": False}),
        "STOPPED:decision",
        "exec:finalizing",
    )


@pytest.mark.unit
def test_vec_v6_019_exec_finalizing_e14_failed() -> None:
    """AC-F.1: E14 → ``STOPPED:decision`` (not DONE) with ``suspended: exec:finalizing``."""
    _stopped(
        _step(
            "exec:finalizing", "E14", {"receipt": "final/1.json", "reason": "validator"}
        ),
        "STOPPED:decision",
        "exec:finalizing",
    )


@pytest.mark.unit
@pytest.mark.parametrize("state", NONTERMINALS)
def test_vec_v6_020_every_nonterminal_e6_budget(state: str) -> None:
    """AC-F.1: E6 in every non-terminal state → ``STOPPED:budget`` with the pending op."""
    res = _step(state, "E6", {"tokens": 1000}, {"pending_op": "op-7"})
    _stopped(res, "STOPPED:budget", state)
    assert res["pending_op"] == "op-7", res
    assert _step(state, "E6", {"tokens": 1000})["pending_op"] == "none"


@pytest.mark.unit
@pytest.mark.parametrize("state", NONTERMINALS)
def test_vec_v6_021_every_nonterminal_e11_unruled(state: str) -> None:
    """AC-F.1: E11 once the gate wait elapsed → ``STOPPED:decision``; before it the wait continues."""
    facts = {"gate_wait_s": 600}
    _stopped(
        _step(state, "E11", {"brief": "d.md", "wait_elapsed": 600}, facts),
        "STOPPED:decision",
        state,
    )
    _stay(_step(state, "E11", {"brief": "d.md", "wait_elapsed": 599}, facts), state)
    for bad_wait in (-1, "600", True):
        bad = _step(state, "E11", {"brief": "d.md", "wait_elapsed": bad_wait}, facts)
        assert (bad["to"], bad["guard_result"]) == (state, "payload_invalid"), bad_wait


@pytest.mark.unit
@pytest.mark.parametrize("state", NONTERMINALS)
def test_vec_v6_022_every_nonterminal_e18_human_stop(state: str) -> None:
    """AC-F.1: E18 once the named row is closed → ``STOPPED:human_stop``; before it the row finishes."""
    payload = {"row": "3", "message_uuid": str(uuid.uuid4())}
    _stopped(
        _step(state, "E18", payload, {"row_closed": True}), "STOPPED:human_stop", state
    )
    _stay(_step(state, "E18", payload, {"row_closed": False}), state)


@pytest.mark.unit
@pytest.mark.parametrize("state", NONTERMINALS)
def test_vec_v6_023_every_nonterminal_e9_not_written(state: str) -> None:
    """AC-F.1: E9 is never a written transition: the step refuses ``monitor_only``."""
    with pytest.raises(Exception) as info:
        _step(state, "E9", {})
    _refusal(info.value, "monitor_only")


@pytest.mark.unit
def test_vec_v6_024_parked_e17_start_exec() -> None:
    """AC-F.1: E17 resumes an ``exec_after_plan`` park into ``plan:pc_done``; then τ3, never τ2 again."""
    parked = {
        "parked_by": "exec_after_plan",
        "suspended": "plan:pc_done",
        "pending_op": "none",
    }
    payload = {"start_record": START, "message_uuid": str(uuid.uuid4())}
    _transitioned(
        _step("PARKED:approved", "E17", payload, {"start_valid": True}, **parked),
        "plan:pc_done",
        "E17",
    )
    _stay(
        _step("PARKED:approved", "E17", payload, {"start_valid": False}, **parked),
        "PARKED:approved",
    )
    _stay(
        _step(
            "PARKED:approved",
            "E17",
            payload,
            {"start_valid": True},
            **{**parked, "parked_by": "authority"},
        ),
        "PARKED:approved",
    )
    after = {"exec_after_plan": False, "e17_recorded": True, "base_matches": True}
    _stay(_step("plan:pc_done", "τ2", {}, after), "plan:pc_done")
    _transitioned(_step("plan:pc_done", "τ3", {}, after), "transition:prepared", "τ3")


@pytest.mark.unit
def test_vec_v6_025_parked_e15_resume() -> None:
    """AC-F.1: E15 on a non-``exec_after_plan`` park re-enters ``suspended``."""
    parked = {
        "parked_by": "authority",
        "suspended": "plan:approved",
        "pending_op": "op-pc",
    }
    payload = {
        "start_record": START,
        "suspended": "plan:approved",
        "pending_op": "op-pc",
    }
    ok = {"resume_valid": True, "authority_ok": True}
    _transitioned(
        _step("PARKED:approved", "E15", payload, ok, **parked), "plan:approved", "E15"
    )
    _stay(
        _step(
            "PARKED:approved",
            "E15",
            payload,
            ok,
            **{**parked, "parked_by": "exec_after_plan"},
        ),
        "PARKED:approved",
    )
    _stay(
        _step(
            "PARKED:approved", "E15", payload, {**ok, "resume_valid": False}, **parked
        ),
        "PARKED:approved",
    )


@pytest.mark.unit
def test_vec_v6_026_stopped_e15_resume() -> None:
    """AC-F.1: E15 on a ``STOPPED:*`` re-enters ``suspended``; a planning-time stop resumes into ``plan:*``."""
    ok = {"resume_valid": True, "authority_ok": True}
    payload = {"start_record": START, "suspended": "exec:active", "pending_op": "none"}
    stopped = {"suspended": "exec:active", "pending_op": "none"}
    _transitioned(
        _step("STOPPED:budget", "E15", payload, ok, **stopped), "exec:active", "E15"
    )
    planning = {"suspended": "plan:approved", "pending_op": "op-pc"}
    _transitioned(
        _step("STOPPED:decision", "E15", {**payload, **planning}, ok, **planning),
        "plan:approved",
        "E15",
    )
    _stay(
        _step(
            "STOPPED:budget", "E15", payload, {**ok, "resume_valid": False}, **stopped
        ),
        "STOPPED:budget",
    )


@pytest.mark.unit
@pytest.mark.parametrize("state", ["STOPPED:no_record", "STOPPED:ambiguous"])
def test_vec_v6_027_no_record_ambiguous_e15_resolution(state: str) -> None:
    """AC-F.1: E15 from ``no_record``/``ambiguous`` needs a resolution: rebuild resumes, discard decides."""
    last = {"suspended": "transition:admitted", "pending_op": "op-exec"}
    payload = {
        "start_record": START,
        "suspended": "transition:admitted",
        "pending_op": "op-exec",
    }
    ok = {"resume_valid": True, "authority_ok": True}
    _transitioned(
        _step(state, "E15", {**payload, "resolution": "rebuild"}, ok, **last),
        "transition:admitted",
        "E15",
    )
    discard = _step(state, "E15", {**payload, "resolution": "discard"}, ok, **last)
    assert discard["to"] == "STOPPED:decision", discard
    _stay(_step(state, "E15", payload, ok, **last), state)


@pytest.mark.unit
def test_vec_v6_028_fork_enters_plan_active() -> None:
    """AC-F.5: E16 from a terminal → a new run in ``plan:active``; a bad slug refuses ``fork_refused``."""
    payload = {"start_record": START, "new_plan": FORK, "new_run_id": FORK_RUN}
    facts = {"plan": bf.PLAN, "fork_verified": True}
    for state in ("PARKED:approved", "STOPPED:budget"):
        res = _step(
            state, "E16", payload, facts, suspended="plan:active", pending_op="none"
        )
        _transitioned(res, "plan:active", "E16")
    with pytest.raises(Exception) as info:
        _step("STOPPED:budget", "E16", {**payload, "new_plan": "other-plan"}, facts)
    _refusal(info.value, "fork_refused")
    with pytest.raises(Exception) as info:
        _step("STOPPED:budget", "E16", payload, {**facts, "fork_verified": False})
    _refusal(info.value, "fork_refused")


@pytest.mark.unit
@pytest.mark.parametrize("event", ["E15", "E16", "E17"])
def test_vec_v6_029_done_is_immutable(event: str) -> None:
    """AC-F.1: E15 / E16 / E17 on ``DONE`` refuse ``done``."""
    with pytest.raises(Exception) as info:
        _step("DONE", event, {"start_record": START}, {"resume_valid": True})
    _refusal(info.value, "done")


@pytest.mark.unit
@pytest.mark.parametrize(
    ("state", "event"),
    [
        ("plan:active", "E3"),
        ("exec:active", "τ1"),
        ("PARKED:approved", "E1"),
        ("STOPPED:decision", "E6"),
        ("DONE", "E1"),
    ],
)
def test_vec_v6_030_unlisted_pair_ignored(state: str, event: str) -> None:
    """AC-F.1: a pair the table does not list is ``ignored`` with ``to = from``."""
    res = _step(state, event, {})
    assert (res["to"], res["guard_result"]) == (state, "ignored"), res


# -- AC-F.1 crash windows ------------------------------------------------------------------


def _crash_window(tmp_path: Path, state: str) -> None:
    """The named successor of E9 in ``state``, and a crash before the record writes nothing."""
    rp = _rp()
    assert rp.PHASE_CRASH_RECOVERY[state] == CRASH_RECOVERY[state]
    fx = _build(tmp_path)
    _init(fx)
    _drive(fx, state)
    before = _transitions(fx)
    view = _state(fx)
    assert view["state"] == state, view
    code = (
        "from pathlib import Path\n"
        "from tools import run_parameters as rp\n"
        f"rp.record_transition(Path({str(fx.repo)!r}), plan={fx.plan!r}, run_id={RUN!r}, "
        "event='E6', payload={'tokens': 1}, by='run')\n"
    )
    proc = fx.run_python(code, env={CRASH: PHASE_CRASH_POINT})
    assert proc.returncode == CRASH_EXIT, (proc.stdout, proc.stderr)
    assert _transitions(fx) == before
    assert _state(fx) == view


def test_vec_v6_031_crash_plan_active(tmp_path: Path) -> None:
    """AC-F.1: a crash in ``plan:active`` re-enters the loop; nothing is written."""
    _crash_window(tmp_path, "plan:active")


def test_vec_v6_032_crash_plan_approved(tmp_path: Path) -> None:
    """AC-F.1: a crash in ``plan:approved`` runs the ``pending_op`` recovery first."""
    _crash_window(tmp_path, "plan:approved")


def test_vec_v6_033_crash_plan_pc_done(tmp_path: Path) -> None:
    """AC-F.1: a crash in ``plan:pc_done`` re-evaluates τ2/τ3."""
    _crash_window(tmp_path, "plan:pc_done")


def test_vec_v6_034_crash_transition_prepared(tmp_path: Path) -> None:
    """AC-F.1: a crash in ``transition:prepared`` re-runs the τ3 admit guards."""
    _crash_window(tmp_path, "transition:prepared")


def test_vec_v6_035_crash_transition_admitted(tmp_path: Path) -> None:
    """AC-F.1: a crash in ``transition:admitted`` re-runs τ4."""
    _crash_window(tmp_path, "transition:admitted")


def test_vec_v6_036_crash_exec_active(tmp_path: Path) -> None:
    """AC-F.1: a crash in ``exec:active`` resumes at the row level."""
    _crash_window(tmp_path, "exec:active")


def test_vec_v6_037_crash_exec_finalizing(tmp_path: Path) -> None:
    """AC-F.1: a crash in ``exec:finalizing`` runs the recovery first."""
    _crash_window(tmp_path, "exec:finalizing")


# -- AC-F.2 phase-aware resume validation --------------------------------------------------


def _resume(state: str, **over: bool) -> tuple[str, ...]:
    return tuple(_msg().phase_resume_check(state, {**RESUME_OK, **over}))


def _groups(state: str) -> None:
    assert dict(_msg().PHASE_RESUME[state]) == RESUME_GROUPS[state]
    assert _resume(state) == ()


@pytest.mark.unit
def test_vec_v6_038_resume_plan_active() -> None:
    """AC-F.2: ``plan:active`` keeps (iii) and (iv): ref == base, the commit grant unset, the start ref."""
    _groups("plan:active")
    assert _resume("plan:active", base_ok=False) == ("base_moved",)
    assert _resume("plan:active", commit_grant_unset=False) == ("commit_grant_env",)
    assert _resume("plan:active", start_ref_ok=False) == ("start_ref_mismatch",)
    assert _resume("plan:active", active_tree_ok=False) == ()


@pytest.mark.unit
def test_vec_v6_039_resume_plan_approved() -> None:
    """AC-F.2: ``plan:approved`` replaces (iii) with ref == P or the op's ``ref_new``."""
    _groups("plan:approved")
    assert _resume("plan:approved", base_ok=False) == ("base_moved",)
    assert _resume("plan:approved", start_ref_ok=False) == ("start_ref_mismatch",)


@pytest.mark.unit
@pytest.mark.parametrize("state", ["plan:pc_done", "transition:prepared"])
def test_vec_v6_040_resume_pc_done_prepared(state: str) -> None:
    """AC-F.2: ``plan:pc_done`` and ``transition:prepared`` need ref == B, the reservation and the binding."""
    _groups(state)
    assert _resume(state, base_ok=False) == ("base_moved",)
    assert _resume(state, reservation_present=False) == ("reservation_missing",)
    assert _resume(state, binding_active=False) == ("binding_inactive",)


@pytest.mark.unit
def test_vec_v6_041_resume_transition_admitted() -> None:
    """AC-F.2: ``transition:admitted`` replaces (i) and keeps (ii): a tree mismatch refuses here."""
    _groups("transition:admitted")
    assert _resume("transition:admitted", worktree_ok=False) == ("worktree_mismatch",)
    assert _resume("transition:admitted", active_tree_ok=False) == (
        "active_tree_mismatch",
    )


@pytest.mark.unit
def test_vec_v6_042_resume_exec_active() -> None:
    """AC-F.2: ``exec:active`` replaces (ii); a removed worktree needs its removal record."""
    _groups("exec:active")
    assert _resume("exec:active", worktree_ok=False) == ("worktree_mismatch",)
    assert _resume("exec:active", worktree_present=False, removal_recorded=True) == ()
    assert _resume("exec:active", worktree_present=False) == ("worktree_lost",)
    assert _resume("exec:active", active_tree_ok=False) == ()
    assert _resume("exec:active", acts_unconsumed=False) == ("act_consumed",)


@pytest.mark.unit
def test_vec_v6_043_resume_exec_finalizing() -> None:
    """AC-F.2: ``exec:finalizing`` replaces (i) and (ii): the removal record, or a refusal."""
    _groups("exec:finalizing")
    assert (
        _resume("exec:finalizing", worktree_present=False, removal_recorded=True) == ()
    )
    assert _resume("exec:finalizing", worktree_present=False) == ("worktree_lost",)
    assert _resume("exec:finalizing", active_tree_ok=False) == ()
    assert _resume("exec:finalizing", base_ok=False) == ("base_moved",)


# -- AC-F.3 credits: manifest, derived view, stop classes ----------------------------------


T0 = datetime(2026, 10, 15, 12, 0, 0, tzinfo=UTC)


def _at(seconds: int) -> str:
    return (T0 + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class _Out:
    code: int
    payload: dict[str, Any]
    text: str


def _cli(db: Path, verb: str, *args: str, now: int = 0) -> _Out:
    """One ``credits_state.py`` call in a subprocess (the store's own CLI contract)."""
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("CREDITS_")}
    env["CREDITS_TEST_EFFECT_LOG"] = str(db.parent / "effects.jsonl")
    proc = subprocess.run(  # noqa: S603 - fixed argv
        [
            sys.executable,
            str(STATE_TOOL),
            "--db",
            str(db),
            "--now-utc",
            _at(now),
            verb,
            *args,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=ROOT,
        timeout=60,
        check=False,
    )
    text = proc.stdout.strip()
    try:
        payload = json.loads(text) if text else {}
    except json.JSONDecodeError:
        payload = {}
    return _Out(
        proc.returncode,
        payload if isinstance(payload, dict) else {},
        proc.stdout + proc.stderr,
    )


def _manifest(root: Path, run_id: str, **extra: Any) -> Path:
    doc: dict[str, Any] = {
        "schema": "credits-run.v1",
        "run_id": run_id,
        "kind": "exec",
        "project_root": "X:/fixture-project",
        "plan_folder": "docs/execution/plans/2026-10-15-fixture/",
        "brief": "C:/Temp/fixture/brief.md",
        "launch": {
            "working_directory": "X:/fixture-project",
            "claude_exe": "C:/fixture/claude.cmd",
            "python_exe": "C:/fixture/python.exe",
            "permission_mode": "bypassPermissions",
            "model": "fixture-model",
            "effort": "high",
            "segment_cap_usd": 75.0,
            "timeout_sec": 43200,
        },
        "budget": {"run_cap_usd": 200.0},
        "messaging": {
            "orchestrator_sessions": ["00000000-0000-4000-8000-0000000000aa"],
            "ruling_enabled": False,
            "gate_wait_max_min": 0,
        },
        "depends_on": [],
        "lane": f"tree:X:/fixture-tree/{run_id}",
        **extra,
    }
    key = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:16]
    path = root / f"manifest-{key}.json"
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return path


def _registered(db: Path, run_id: str, **extra: Any) -> None:
    manifest = _manifest(db.parent, run_id, **extra)
    out = _cli(
        db,
        "register",
        "--run-id",
        run_id,
        "--manifest",
        str(manifest),
        "--cli-version",
        "9.9.9",
        "--kit-revision",
        "kitrev-fixture",
    )
    assert out.code == 0, out.text
    out = _cli(
        db, "registered", "--run-id", run_id, "--task-hash", f"taskhash-{run_id}"
    )
    assert out.code == 0, out.text


def test_vec_v6_044_manifest_phases_and_run_id(tmp_path: Path) -> None:
    """AC-F.3: the manifest carries ``phases`` and ``run_id``; a legacy manifest reads ``()``."""
    cs = _cs()
    schema = json.loads(CREDITS_SCHEMA.read_text(encoding="utf-8"))
    assert "phases" in schema["properties"], sorted(schema["properties"])
    phased = cs.load_manifest(
        str(_manifest(tmp_path, "run-p", phases=["plan", "exec"])), "run-p"
    )
    assert tuple(phased.phases) == ("plan", "exec")
    legacy = cs.load_manifest(str(_manifest(tmp_path, "run-l")), "run-l")
    assert tuple(legacy.phases) == ()
    for bad in (["plan", "plan"], [], ["plan", "review"], "plan"):
        with pytest.raises(cs.Refusal) as info:
            cs.load_manifest(str(_manifest(tmp_path, "run-b", phases=bad)), "run-b")
        assert info.value.error == "manifest_invalid", bad
    fx = _build(tmp_path, "credits", profile="credits")
    credits = fx.root / "credits"
    run_id = json.loads((credits / "manifest.json").read_text(encoding="utf-8"))[
        "run_id"
    ]
    loaded = cs.load_manifest(str(credits / "manifest.json"), run_id)
    assert tuple(loaded.phases) == ("plan", "exec")
    brief = (credits / "brief.md").read_text(encoding="utf-8")
    assert "## Authorization" in brief
    assert "```yaml\nrun_parameters:" in brief
    plain = _build(tmp_path, "plain")
    assert not (plain.root / "credits").exists()


def test_vec_v6_045_records_and_derived_view(tmp_path: Path) -> None:
    """AC-F.1: records chain by ``from_seq``; a failed guard is a stay; the views follow the record."""
    fx = _build(tmp_path)
    _init(fx)
    head = bf.git(fx.repo, "rev-parse", "HEAD")
    first = _record(fx, "E1", {"verdict_path": _write_verdict(fx)})
    assert (first["seq"], first["from"], first["from_seq"], first["to"]) == (
        1,
        "plan:active",
        0,
        "plan:approved",
    )
    second = _record(
        fx, "E3", {"op_id": "op-pc", "ref_new": head}, facts=PC_FACTS, op_id="op-pc"
    )
    assert (second["seq"], second["from"], second["from_seq"], second["to"]) == (
        2,
        "plan:approved",
        1,
        "plan:pc_done",
    )
    records = _transitions(fx)
    assert [r["seq"] for r in records] == [1, 2]
    _schema_valid("op", "run-parameters-op", {"transitions": records})
    assert _state(fx) == {"state": "plan:pc_done", "seq": 2}
    view = json.loads(_ops_file(fx, "state.json").read_text(encoding="utf-8"))
    assert (view["state"], view["seq"]) == ("plan:pc_done", 2)

    other = "run-fixture-2"
    stay = _record(
        fx,
        "E1",
        {
            "verdict_path": f".agent/context/handoffs/{bf.PLAN_B}-plan-critical-review.md"
        },
        run_id=other,
    )
    assert (stay["from"], stay["to"], stay["guard_result"]) == (
        "plan:active",
        "plan:active",
        "guard_failed:verdict",
    )
    assert len(_transitions(fx, run_id=other)) == 1
    assert _state(fx, run_id=other) == {"state": "plan:active", "seq": 0}

    cs = _cs()
    assert cs.SCHEMA_VERSION == 7
    db = tmp_path / "store" / "state.db"
    db.parent.mkdir()
    assert _cli(db, "init").code == 0
    _registered(db, "run-v", phases=["plan", "exec"])
    _registered(db, "run-legacy")
    out = _cli(
        db, "phase_sync", "--run-id", "run-v", "--state", "plan:pc_done", "--seq", "2"
    )
    assert out.code == 0, out.text
    out = _cli(db, "phase_status", "--run-id", "run-v")
    assert out.code == 0, out.text
    assert (out.payload["phase_state"], out.payload["phase_seq"]) == ("plan:pc_done", 2)
    out = _cli(
        db,
        "phase_status",
        "--run-id",
        "run-v",
        "--expect-state",
        "plan:pc_done",
        "--expect-seq",
        "2",
    )
    assert out.code == 0, out.text
    out = _cli(
        db,
        "phase_status",
        "--run-id",
        "run-v",
        "--expect-state",
        "plan:approved",
        "--expect-seq",
        "1",
    )
    assert (out.code, out.payload.get("error")) == (3, "state_mismatch"), out.text
    out = _cli(db, "phase_status", "--run-id", "run-legacy")
    assert out.code == 0, out.text
    assert out.payload["phase_state"] is None, out.payload


def test_vec_v6_046_priority_and_serialized_record(tmp_path: Path) -> None:
    """AC-F.1: one event per transaction by priority; a stale ``from_seq`` is re-evaluated."""
    rp = _rp()
    assert rp.pick_event(["τ3", "E6", "E18"]) == "E18"
    assert rp.pick_event(["E5", "E18"]) == "E5"
    assert rp.pick_event(["E1", "τ1"]) == "E1"
    assert rp.pick_event(["E11", "E2", "E6"]) == "E6"
    with pytest.raises(ValueError):
        rp.pick_event(["E15", "E6"])
    fx = _build(tmp_path)
    _init(fx)
    _drive(fx, "transition:prepared")
    seen = _transitions(fx)[-1]["seq"]
    _mark_row(fx, "0")
    stop = _record(fx, "E18", {"row": "0", "message_uuid": str(uuid.uuid4())})
    assert (stop["to"], stop["suspended"]) == (
        "STOPPED:human_stop",
        "transition:prepared",
    )
    late = _record(fx, "τ3", {}, facts=ADMIT_FACTS, from_seq=seen, op_id="op-exec")
    assert (late["from"], late["to"], late["guard_result"]) == (
        "STOPPED:human_stop",
        "STOPPED:human_stop",
        "ignored",
    )
    assert late["from_seq"] == stop["seq"], late
    assert _state(fx)["state"] == "STOPPED:human_stop"


def test_vec_v6_048_removal_records(tmp_path: Path) -> None:
    """AC-F.1: the H2-3c removal records are written while ``exec:active``, in order."""
    rp = _rp()
    fx = _build(tmp_path)
    _init(fx)
    path = "{{PROJECT_ROOT}}-wt/fixture-run"
    digest = "c" * 64

    def remove(event: str, run_id: str = RUN) -> dict[str, Any]:
        with bf.patched_environ(fx.env()):
            return dict(
                rp.record_removal(
                    fx.repo,
                    plan=fx.plan,
                    run_id=run_id,
                    event=event,
                    path=path,
                    manifest_digest=digest,
                    by="executor_worktree.py remove",
                    row="H2-3c",
                )
            )

    with pytest.raises(Exception) as info:
        remove("worktree_removal_started")
    _refusal(info.value, "phase_state")
    _drive(fx, "exec:active")
    started = remove("worktree_removal_started")
    removed = remove("worktree_removed")
    assert (started["event"], removed["event"]) == (
        "worktree_removal_started",
        "worktree_removed",
    )
    with bf.patched_environ(fx.env()):
        listed = [dict(r) for r in rp.phase_removals(fx.repo, plan=fx.plan, run_id=RUN)]
    assert [r["event"] for r in listed] == [
        "worktree_removal_started",
        "worktree_removed",
    ]
    assert listed[0]["manifest_digest"] == digest
    data = json.loads(_ops_file(fx, "removal.json").read_text(encoding="utf-8"))
    assert len(data["removals"]) == 2
    _drive(fx, "exec:active", run_id="run-fixture-2")
    with pytest.raises(Exception) as info:
        remove("worktree_removed", run_id="run-fixture-2")
    _refusal(info.value, "removal_order")


def _transcript(fx: bf.Fixture, minutes_old: int) -> Path:
    path = fx.root / "segment-transcript.jsonl"
    path.write_text('{"type": "system"}\n', encoding="utf-8")
    clock = datetime.strptime(bf.FIXTURE_CLOCK, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=UTC
    )
    stamp = (clock - timedelta(minutes=minutes_old)).timestamp()
    os.utime(path, (stamp, stamp))
    return path


def _stop_no_record(fx: bf.Fixture, seq: int, transcript: Path) -> Result:
    return fx.run(
        "stop",
        "--plan",
        fx.plan,
        "--run",
        RUN,
        "--reason",
        "no_record",
        "--expect-seq",
        str(seq),
        "--pid",
        str(fx.dead_pid()),
        "--pid-start",
        "fixture-start",
        "--transcript",
        str(transcript),
    )


def test_vec_v6_049_no_record_stop_contract(tmp_path: Path) -> None:
    """AC-F.3: ``stop --reason no_record`` re-checks the four conditions under the lock and records E9."""
    fx = _build(tmp_path)
    _init(fx)
    _drive(fx, "exec:active")
    seq = _transitions(fx)[-1]["seq"]
    young = _stop_no_record(fx, seq, _transcript(fx, 5))
    _refused(young, "no_record_not_met", effective=False)
    late = _stop_no_record(fx, seq - 1, _transcript(fx, 20))
    _refused(late, "no_record_not_met", effective=False)

    task_before = fx.task_path().read_bytes()
    ops_before = _ops_file(fx, "transitions.json").read_bytes()
    _stale_lock(fx)
    code, out = _stop_no_record(fx, seq, _transcript(fx, 20))
    assert (code, out.get("result")) == (1, "refused"), out
    assert out.get("reason") in ("stale_lock", "txn_pending"), out
    assert fx.task_path().read_bytes() == task_before
    assert _ops_file(fx, "transitions.json").read_bytes() == ops_before
    (fx.store / "store.lock").unlink()

    code, out = _stop_no_record(fx, seq, _transcript(fx, 20))
    assert (code, out.get("result"), out.get("state")) == (
        0,
        "stopped",
        "STOPPED:no_record",
    ), out
    last = _transitions(fx)[-1]
    assert (last["event"], last["by"], last["to"], last["suspended"]) == (
        "E9",
        "monitor",
        "STOPPED:no_record",
        "exec:active",
    )
    assert _frontmatter(fx.task_path())["stop_gate"] == "released:human-gate"
    assert _state(fx)["state"] == "STOPPED:no_record"


def test_vec_v6_051_resume_brief_template() -> None:
    """AC-F.3: the resume brief copies the ``run_parameters`` block and states the worktree rule."""
    text = RESUME_BRIEF.read_text(encoding="utf-8")
    assert "## Authorization" in text
    assert "```yaml\nrun_parameters:" in text
    assert "executor worktree" in text


@pytest.mark.parametrize(
    ("state", "expect"),
    [("exec:active", "STOPPED:decision"), ("plan:approved", "PARKED:approved")],
)
def test_vec_v6_052_resume_reverifies_authority(
    tmp_path: Path, state: str, expect: str
) -> None:
    """AC-F.2: E15 re-runs V-0 to V-10: a refusal after execution began stops, before it parks."""
    fx = _build(tmp_path)
    _init(fx)
    _drive(fx, state)
    budget = _record(fx, "E6", {"tokens": 1})
    assert (budget["to"], budget["suspended"]) == ("STOPPED:budget", state)
    _corrupt_grant(fx)
    res = _record(
        fx,
        "E15",
        {"start_record": START, "suspended": state, "pending_op": "none"},
        facts={"resume_valid": True},
    )
    assert res["to"] == expect, res
    if expect == "PARKED:approved":
        assert res["parked_by"] == "authority", res


# -- AC-F.4 binding context ----------------------------------------------------------------


def test_bind_context_is_persisted_and_owned(tmp_path: Path) -> None:
    """AC-F.4: ``bind --context`` persists; no flag keeps it; a different flag refuses ``binding``."""
    fx = _build(tmp_path)
    _init(fx)
    session = fx.session
    code, out = fx.run(
        "bind", "--pending", fx.plan, "--session", session, "--context", "headless"
    )
    assert code == 0, out
    assert _session_record(fx, session)["context"] == "headless"
    before = fx.read_json(f"sessions/{session}.json")
    res = fx.run(
        "bind", "--plan", fx.plan, "--session", session, "--context", "interactive"
    )
    _refused(res, "binding", effective=False)
    assert fx.read_json(f"sessions/{session}.json") == before
    code, out = fx.run("bind", "--plan", fx.plan, "--session", session)
    assert code == 0, out
    assert _session_record(fx, session)["context"] == "headless"

    other = _build(tmp_path, "env")
    _init(other)
    code, out = other.run(
        "bind",
        "--pending",
        other.plan,
        "--session",
        other.session,
        env={"CLAUDE_CODE_ENTRYPOINT": "sdk-cli"},
    )
    assert code == 0, out
    assert _session_record(other, other.session)["context"] == "interactive"


def _bound(tmp_path: Path, name: str, d20: str, context: str) -> bf.Fixture:
    fx = _build(tmp_path, name)
    fx.write_policy(
        rulings={"d19": "A", "d20": d20}, capabilities=bf.capabilities_for(d20)
    )
    fx.commit(f"fixture policy d20 {d20}")
    _init(fx)
    for verb in ("--pending", "--plan"):
        code, out = fx.run(
            "bind", verb, fx.plan, "--session", fx.session, "--context", context
        )
        assert code == 0, out
    return fx


def test_d20_b_headless_binding_refuses_interactive_acts(tmp_path: Path) -> None:
    """AC-F.4: under ``d20: B`` a headless binding refuses ``plan_commit`` and ``finalize`` (``capability``)."""
    fx = _bound(tmp_path, "b-headless", "B", "headless")
    _refused(_verify(fx, "plan_commit"), "capability")
    _refused(_verify(fx, "finalize"), "capability")
    _verified(_verify(fx, "exec_start"))
    _verified(
        _verify(_bound(tmp_path, "b-interactive", "B", "interactive"), "plan_commit")
    )
    _verified(_verify(_bound(tmp_path, "a-headless", "A", "headless"), "plan_commit"))


# -- AC-F.5 fork ---------------------------------------------------------------------------


def test_fork_cannot_reuse_a_consumed_act(tmp_path: Path) -> None:
    """AC-F.5: the fork's first record is its own; the original is unchanged; consumed acts stay consumed."""
    fx = _build(tmp_path)
    block = fx.present_and_accept(values=fx.standing_offer([bf.PLAN, FORK]))
    fx.write_carrier(block, plan=bf.PLAN)
    fx.write_carrier(block, plan=FORK)
    _init(fx)
    code, out = _reserve(fx, "exec_commit", "op-1")
    assert (code, out.get("result")) == (0, "reserved"), out
    budget = _record(fx, "E6", {"tokens": 1})
    assert budget["to"] == "STOPPED:budget", budget
    original = _ops_file(fx, "transitions.json").read_bytes()
    fork = _record(
        fx, "E16", {"start_record": START, "new_plan": FORK, "new_run_id": FORK_RUN}
    )
    assert _ops_file(fx, "transitions.json").read_bytes() == original
    records = _transitions(fx, plan=FORK, run_id=FORK_RUN)
    assert records == [fork], records
    assert (fork["seq"], fork["from"], fork["from_seq"], fork["to"]) == (
        1,
        "STOPPED:budget",
        0,
        "plan:active",
    )
    assert fork["payload"]["forked_from"] == {
        "plan": bf.PLAN,
        "run_id": RUN,
        "seq": budget["seq"],
    }
    _schema_valid("op", "run-parameters-op", {"transitions": records})
    _refused(_reserve(fx, "exec_commit", "op-f", plan=FORK), "consumed")
    code, out = _reserve(fx, "exec_start", "op-f", plan=FORK)
    assert (code, out.get("result")) == (0, "reserved"), out

    lone = _build(tmp_path, "lone")
    _init(lone)
    _record(lone, "E6", {"tokens": 1})
    before = _ops_file(lone, "transitions.json").read_bytes()
    with pytest.raises(Exception) as info:
        _record(
            lone,
            "E16",
            {
                "start_record": START,
                "new_plan": f"{bf.PLAN}-fork-2",
                "new_run_id": "run-f2",
            },
        )
    _refusal(info.value, "fork_refused")
    assert _ops_file(lone, "transitions.json").read_bytes() == before
