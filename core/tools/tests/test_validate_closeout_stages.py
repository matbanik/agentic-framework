"""B-4: the closeout stages, the final receipt and the publication audit (AC-D.3, AC-D.4).

Plan: the run-parameters design plan (B-4; report R§4.6 "Check-by-stage
matrix", "final audit and seal", App F item 5). Vectors V4-007 to V4-018 and V4-021 to V4-035.

The tests fix this contract (EA-13):

* ``tools.validate_closeout_artifacts`` gains ``STAGES``, ``PENDING_SETS``, ``STAGE_CHECKS`` (the
  fifteen matrix rows of R§4.6 in order), ``STAGE_MATRIX`` (``{check: (structural, readiness,
  final)}``) and ``validate_stage(args, stage, *, for_produce=False)``. It returns
  ``{"status", "mode": "stage", "stage", "checks", "failures", "foreign_movement"}``; each check
  is ``pass``, ``fail``, ``n/a`` or ``deferred``. An unknown stage raises ``ValueError``. The CLI
  gains ``--stage`` with ``--commit-manifest``, ``--repo`` and ``--plan-slug``.
* For a plan that carries a ``run_parameters`` block the stage reads the run's authority through
  two module seams: ``plan_inspect(repo, plan)`` (the ``inspect`` report: the grant and the ops)
  and ``plan_audit(repo, plan)`` (the publication audit and the receipt state). A legacy plan
  calls neither and reports the four run-only checks ``n/a``. ``commit_exec: false`` has no commit
  manifest, no commit ops and no publication, so those three are ``n/a``; the receipt still
  applies at ``final``. ``for_produce=True`` is the call ``final --produce`` makes before the
  receipt exists: the audit and the receipt are ``deferred`` and ``plan_audit`` is never called.
* ``tools.run_parameters`` gains ``final_read_set(repo, plan)``, ``publication_audit(repo, branch,
  publications)``, the seam ``run_stage_validators`` and the verbs ``final --produce``, ``final
  --seal``, ``status --plan`` and ``repair --final``.

Every fixture is built inside the test body, and every module is imported there, so a missing
name fails the test rather than the collection.
"""

from __future__ import annotations

import base64
import copy
import importlib
import json
import uuid
from argparse import Namespace
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

import jsonschema
import pytest
import yaml

from tools.tests.run_parameters_fixtures import build_fixture as bf
from tools.tests.run_parameters_fixtures.closeout_cases import (
    SCRATCH_CITATION,
    VACUOUS_H23_FIXTURE,
    WRONG_TARGET_PLAN,
    _full_closeout_args,
)

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / bf.RUN_PARAMETERS_HOME / "schemas"
STAGES = ("structural", "readiness", "final")
STAGE_STATUS = {
    "structural": "in_progress",
    "readiness": "in_progress",
    "final": "complete",
}
STAGE_GATE = {"structural": "armed", "readiness": "armed", "final": "released:done"}
PENDING = {
    "structural": {"H2-4", "H2-5", "COMMIT", "H2-6"},
    "readiness": {"H2-5", "COMMIT", "H2-6"},
    "final": set(),
}
ROWS = ("H1-7", "H2-1", "H2-2", "H2-3", "H2-4", "H2-5", "COMMIT", "H2-6")
CHECKS = (
    "required_inputs",
    "task_closeout",
    "plan_task_status",
    "handoff_ac",
    "approved_review",
    "reflection_decisions",
    "metrics_context",
    "provenance_citations",
    "pending_rows",
    "commit_manifest",
    "stop_gate",
    "run_parameters",
    "commit_ops",
    "publication_audit",
    "receipt_generation",
)
ALL = (True, True, True)
MATRIX = {
    **{check: ALL for check in CHECKS},
    "commit_manifest": (False, True, True),
    "commit_ops": (False, True, True),
    "publication_audit": (False, False, True),
    "receipt_generation": (False, False, True),
}
RUN_ONLY = ("commit_manifest", "commit_ops", "publication_audit", "receipt_generation")
TASK_HEADER = (
    "| # | Task | Owner | Deliverable | Validation | Depends on | Status |\n"
    "| :- | :- | :- | :- | :- | :- | :- |\n"
)
VALIDATOR = {"exit": 0, "version": "fixture", "sha256": "a" * 64}
VALIDATORS = {"closeout": VALIDATOR, "preflight": VALIDATOR}
MANIFEST_PATH = "docs/closeout.md"


def _vca() -> ModuleType:
    return importlib.import_module("tools.validate_closeout_artifacts")


def _rp() -> ModuleType:
    return importlib.import_module("tools.run_parameters")


def _frontmatter(meta: dict[str, Any], body: str) -> bytes:
    return (bf.frontmatter(meta) + body).encode("utf-8")


def _split(path: Path) -> tuple[dict[str, Any], str]:
    head, body = path.read_text(encoding="utf-8").split("---\n", 2)[1:]
    return yaml.safe_load(head), body


# -- the stage case ------------------------------------------------------------------------


@dataclass
class Case:
    """One stage call: the closeout arguments, both carriers, the seams' reports."""

    stage: str
    args: Namespace
    block: dict[str, Any] | None
    session: str
    marks: dict[str, str]
    task_meta: dict[str, Any]
    plan_meta: dict[str, Any]
    inspect: dict[str, Any]
    audit: dict[str, Any]
    plan_acs: list[str] = field(default_factory=lambda: ["AC-303-E1"])
    cells: dict[str, dict[str, str]] = field(default_factory=dict)
    tail: str = ""

    def row(self, row: str) -> str:
        cell = {
            "task": "task",
            "validation": "`command`",
            "depends": "none",
            **self.cells.get(row, {}),
        }
        return (
            f"| {row} | {cell['task']} | tester | `artifact` | {cell['validation']} "
            f"| {cell['depends']} | {self.marks[row]} |\n"
        )

    def write(self) -> None:
        """Write the task and the plan from the case's fields."""
        task_body = (
            "\n# Task\n\n"
            + TASK_HEADER
            + "".join(self.row(r) for r in ROWS)
            + self.tail
        )
        self.args.task.write_bytes(_frontmatter(self.task_meta, task_body))
        plan_body = "\n| AC | Type |\n|----|------|\n" + "".join(
            f"| {ac} | integration |\n" for ac in self.plan_acs
        )
        self.args.plan.write_bytes(_frontmatter(self.plan_meta, plan_body))


def _ops(stage: str, commit_exec: bool) -> list[dict[str, str]]:
    if stage != "final" or not commit_exec:
        return []
    return [
        {"op": "op-exec", "act": "exec_commit", "phase": "reconciled"},
        {"op": "op-final", "act": "finalize", "phase": "reconciled"},
    ]


def _write_manifest(path: Path, repo: Path, data: bytes) -> None:
    packet = {
        "schema": "commit-packet/1",
        "plan": bf.PLAN,
        "branch": "main",
        "parent": bf.git(repo, "rev-parse", "HEAD"),
        "message": "docs(fixture): close out the fixture plan",
        "author": {"name": "Fixture", "email": "fixture@example.invalid"},
        "signing_fingerprint": "fixture",
        "entries": [
            {
                "path": MANIFEST_PATH,
                "mode": "100644",
                "data": base64.b64encode(data).decode("ascii"),
            }
        ],
    }
    path.write_text(json.dumps(packet, indent=2) + "\n", encoding="utf-8")


def _case(
    tmp_path: Path, stage: str, *, legacy: bool = False, commit_exec: bool = True
) -> Case:
    """A stage case that passes: every matrix check ``pass`` or ``n/a``."""
    closeout = tmp_path / "closeout"
    closeout.mkdir(parents=True)
    args = _full_closeout_args(closeout)
    args.handoff = [args.handoff]
    args.commit_manifest = None
    args.repo = None
    args.plan_slug = bf.PLAN
    block: dict[str, Any] | None = None
    session = str(uuid.uuid4())
    if not legacy:
        fx = bf.build(tmp_path / "fx", ROOT)
        block = fx.block if commit_exec else fx.present_and_accept(commit_exec=False)
        session = fx.session
        args.repo = fx.repo
        if commit_exec:
            data = b"# Closeout\n"
            fx.write_text(MANIFEST_PATH, data.decode("utf-8"))
            args.commit_manifest = closeout / "commit-packet.json"
            _write_manifest(args.commit_manifest, fx.repo, data)
    task_meta: dict[str, Any] = {
        "status": STAGE_STATUS[stage],
        "template_version": "2.4",
        "stop_gate": STAGE_GATE[stage],
    }
    plan_meta: dict[str, Any] = {
        "plan": bf.PLAN,
        "template_version": "2.3",
        "status": STAGE_STATUS[stage],
    }
    if block is not None:
        task_meta["run_parameters"] = copy.deepcopy(block)
        task_meta["bound_sessions"] = [session]
        plan_meta["run_parameters"] = copy.deepcopy(block)
    case = Case(
        stage=stage,
        args=args,
        block=block,
        session=session,
        marks={row: "[ ]" if row in PENDING[stage] else "[x]" for row in ROWS},
        task_meta=task_meta,
        plan_meta=plan_meta,
        inspect={"grant": "verified", "consumed": [], "ops": _ops(stage, commit_exec)},
        audit={
            "publication_audit": {"result": "passed", "foreign_movement": []},
            "receipt": "current",
        },
    )
    case.write()
    return case


def _run(
    case: Case,
    monkeypatch: pytest.MonkeyPatch,
    *,
    for_produce: bool = False,
    seams: bool = True,
) -> dict[str, Any]:
    """``validate_stage`` with the two seams patched; ``seams=False`` makes them raise."""
    vca = _vca()
    calls: list[str] = []

    def plan_inspect(repo: Path, plan: str) -> dict[str, Any]:
        assert seams, "a legacy plan read the run's authority"
        calls.append(f"inspect {plan}")
        return copy.deepcopy(case.inspect)

    def plan_audit(repo: Path, plan: str) -> dict[str, Any]:
        assert seams and not for_produce, "plan_audit ran where it must not"
        calls.append(f"audit {plan}")
        return copy.deepcopy(case.audit)

    monkeypatch.setattr(vca, "plan_inspect", plan_inspect, raising=False)
    monkeypatch.setattr(vca, "plan_audit", plan_audit, raising=False)
    out = vca.validate_stage(case.args, case.stage, for_produce=for_produce)
    assert out["mode"] == "stage" and out["stage"] == case.stage, out
    assert list(out["checks"]) == list(CHECKS), out
    return dict(out)


def _expected(check: str, stage: str) -> str:
    return "pass" if MATRIX[check][STAGES.index(stage)] else "n/a"


def _assert_base(out: dict[str, Any], stage: str) -> None:
    assert out["status"] == "PASS", out
    assert out["checks"] == {check: _expected(check, stage) for check in CHECKS}, out


# -- the matrix mutations -----------------------------------------------------------------


def _m_required_inputs(case: Case) -> None:
    case.args.review_state_receipt.unlink()


def _m_task_closeout(case: Case) -> None:
    case.cells["H2-1"] = {"validation": f"`{VACUOUS_H23_FIXTURE}`"}


def _m_plan_task_status(case: Case) -> None:
    case.plan_meta["status"] = "draft"


def _m_handoff_ac(case: Case) -> None:
    case.plan_acs.append("AC-303-E2")


def _m_approved_review(case: Case) -> None:
    case.args.expected_target_plan = WRONG_TARGET_PLAN


def _m_reflection_decisions(case: Case) -> None:
    path: Path = case.args.reflection
    text = path.read_text(encoding="utf-8")
    assert "### Decisions Log\nNone.\n" in text
    path.write_text(text.replace("### Decisions Log\nNone.\n", ""), encoding="utf-8")


def _m_metrics_context(case: Case) -> None:
    path: Path = case.args.metrics
    head = path.read_text(encoding="utf-8").splitlines(keepends=True)[:2]
    path.write_text("".join(head), encoding="utf-8")


def _m_provenance_citations(case: Case) -> None:
    path: Path = case.args.handoff[0]
    sentence = f"\nThe receipt is at {SCRATCH_CITATION} today.\n"
    path.write_text(path.read_text(encoding="utf-8") + sentence, encoding="utf-8")


def _m_pending_rows(case: Case) -> None:
    case.marks["H2-1"] = "[ ]"


def _m_commit_manifest(case: Case) -> None:
    if case.args.commit_manifest is not None:
        _write_manifest(case.args.commit_manifest, case.args.repo, b"# Other bytes\n")


def _m_stop_gate(case: Case) -> None:
    case.task_meta["stop_gate"] = "released:round-cap"


def _m_run_parameters(case: Case) -> None:
    block = case.task_meta["run_parameters"]
    block["authorization"]["message_uuid"] = str(uuid.uuid4())


def _m_commit_ops(case: Case) -> None:
    case.inspect["ops"].append(
        {"op": "op-mid", "act": "exec_commit", "phase": "published"}
    )


def _m_publication_audit(case: Case) -> None:
    case.audit["publication_audit"]["result"] = "ambiguous"


def _m_receipt_generation(case: Case) -> None:
    case.audit["receipt"] = "stale"


MUTATIONS: dict[str, Callable[[Case], None]] = {
    "required_inputs": _m_required_inputs,
    "task_closeout": _m_task_closeout,
    "plan_task_status": _m_plan_task_status,
    "handoff_ac": _m_handoff_ac,
    "approved_review": _m_approved_review,
    "reflection_decisions": _m_reflection_decisions,
    "metrics_context": _m_metrics_context,
    "provenance_citations": _m_provenance_citations,
    "pending_rows": _m_pending_rows,
    "commit_manifest": _m_commit_manifest,
    "stop_gate": _m_stop_gate,
    "run_parameters": _m_run_parameters,
    "commit_ops": _m_commit_ops,
    "publication_audit": _m_publication_audit,
    "receipt_generation": _m_receipt_generation,
}


def _matrix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, check: str, stage: str
) -> None:
    """The base case passes; the mutation fails ``check`` exactly where the matrix marks it."""
    case = _case(tmp_path, stage)
    _assert_base(_run(case, monkeypatch), stage)
    MUTATIONS[check](case)
    case.write()
    out = _run(case, monkeypatch)
    if MATRIX[check][STAGES.index(stage)]:
        assert out["status"] == "FAIL", out
        assert out["checks"][check] == "fail", out
        assert out["failures"].get(check), out
    else:
        assert out["status"] == "PASS", out
        assert out["checks"][check] == "n/a", out


# -- the module contract (AC-D.3) ---------------------------------------------------------


def test_stage_constants_match_the_matrix() -> None:
    """AC-D.3: the stages, their pending sets and the fifteen checks of R§4.6 in order."""
    vca = _vca()
    assert tuple(vca.STAGES) == STAGES
    assert {stage: set(rows) for stage, rows in vca.PENDING_SETS.items()} == PENDING
    assert tuple(vca.STAGE_CHECKS) == CHECKS
    assert {k: tuple(v) for k, v in vca.STAGE_MATRIX.items()} == MATRIX


def test_stage_unknown_stage_raises(tmp_path: Path) -> None:
    """AC-D.3: a stage outside the three is a usage error, never a silent pass."""
    vca = _vca()
    case = _case(tmp_path, "structural", legacy=True)
    with pytest.raises(ValueError, match="bogus"):
        vca.validate_stage(case.args, "bogus")


@pytest.mark.parametrize("stage", STAGES)
def test_stage_legacy_plan_reads_no_run_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    """AC-D.3: a plan with no block passes each stage; the four run-only checks are n/a."""
    case = _case(tmp_path, stage, legacy=True)
    out = _run(case, monkeypatch, seams=False)
    assert out["status"] == "PASS", out
    for check in CHECKS:
        expected = "n/a" if check in RUN_ONLY else "pass"
        assert out["checks"][check] == expected, (check, out)


# -- the matrix rows (V4-021 to V4-035) ---------------------------------------------------


@pytest.mark.parametrize("stage", STAGES)
def test_vec_v4_021_required_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    """AC-D.3: a missing review-state receipt fails required inputs at every stage."""
    _matrix(tmp_path, monkeypatch, "required_inputs", stage)


@pytest.mark.parametrize("stage", STAGES)
def test_vec_v4_022_task_closeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    """AC-D.3: a vacuous Validation cell fails the task closeout at every stage."""
    _matrix(tmp_path, monkeypatch, "task_closeout", stage)


@pytest.mark.parametrize("stage", STAGES)
def test_vec_v4_023_plan_task_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    """AC-D.3: PLAN_TASK_STATUS: the plan and the task status must equal the stage status."""
    _matrix(tmp_path, monkeypatch, "plan_task_status", stage)


@pytest.mark.parametrize("stage", STAGES)
def test_vec_v4_024_handoff_ac(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    """AC-D.3: a plan AC the handoff does not cover fails at every stage."""
    _matrix(tmp_path, monkeypatch, "handoff_ac", stage)


@pytest.mark.parametrize("stage", STAGES)
def test_vec_v4_025_approved_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    """AC-D.3: a review bound to another plan fails at every stage."""
    _matrix(tmp_path, monkeypatch, "approved_review", stage)


@pytest.mark.parametrize("stage", STAGES)
def test_vec_v4_026_reflection_decisions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    """AC-D.3: a reflection with no Decisions Log fails at every stage."""
    _matrix(tmp_path, monkeypatch, "reflection_decisions", stage)


@pytest.mark.parametrize("stage", STAGES)
def test_vec_v4_027_metrics_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    """AC-D.3: a metrics file with no row for the run fails at every stage."""
    _matrix(tmp_path, monkeypatch, "metrics_context", stage)


@pytest.mark.parametrize("stage", STAGES)
def test_vec_v4_028_provenance_citations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    """AC-D.3: a handoff citing the scratch folder in prose fails at every stage."""
    _matrix(tmp_path, monkeypatch, "provenance_citations", stage)


@pytest.mark.parametrize("stage", STAGES)
def test_vec_v4_029_pending_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    """AC-D.3: a row open outside the stage's pending set fails at every stage."""
    _matrix(tmp_path, monkeypatch, "pending_rows", stage)


@pytest.mark.parametrize("stage", STAGES)
def test_vec_v4_030_commit_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    """AC-D.3: a manifest blob that differs from the tree fails readiness and final only."""
    _matrix(tmp_path, monkeypatch, "commit_manifest", stage)


@pytest.mark.parametrize("stage", STAGES)
def test_vec_v4_031_stop_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    """AC-D.3: a stop_gate other than the stage's value fails at every stage."""
    _matrix(tmp_path, monkeypatch, "stop_gate", stage)


@pytest.mark.parametrize("stage", STAGES)
def test_vec_v4_032_run_parameters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    """AC-D.3: carriers whose authorizations differ fail at every stage."""
    _matrix(tmp_path, monkeypatch, "run_parameters", stage)


@pytest.mark.parametrize("stage", STAGES)
def test_vec_v4_033_commit_ops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    """AC-D.3: an op left mid-way fails readiness and final only."""
    _matrix(tmp_path, monkeypatch, "commit_ops", stage)


@pytest.mark.parametrize("stage", STAGES)
def test_vec_v4_034_publication_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    """AC-D.3: an ambiguous publication audit fails final only."""
    _matrix(tmp_path, monkeypatch, "publication_audit", stage)


@pytest.mark.parametrize("stage", STAGES)
def test_vec_v4_035_receipt_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    """AC-D.3: a stale receipt generation fails final only."""
    _matrix(tmp_path, monkeypatch, "receipt_generation", stage)


# -- the final stage (V4-007, V4-008, V4-009, V4-012 to V4-015) -----------------------------


def test_vec_v4_007_provisional_h2_6_mark_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-D.3: H2-6 ``[x]`` stays provisional while the finalize op is not reconciled."""
    case = _case(tmp_path, "final")
    case.inspect["ops"][1]["phase"] = "published"
    out = _run(case, monkeypatch)
    assert out["status"] == "FAIL", out
    assert "provisional_mark" in out["failures"].get("pending_rows", ""), out


def test_vec_v4_008_complete_task_without_receipt_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-D.3: a ``complete`` task with no final receipt fails the final stage."""
    case = _case(tmp_path, "final")
    case.audit["receipt"] = "missing"
    out = _run(case, monkeypatch)
    assert out["status"] == "FAIL", out
    assert out["checks"]["receipt_generation"] == "fail", out


def test_vec_v4_009_stale_receipt_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-D.3: a receipt whose generation is stale names ``stale_generation``."""
    case = _case(tmp_path, "final")
    case.audit["receipt"] = "stale"
    out = _run(case, monkeypatch)
    assert "stale_generation" in out["failures"].get("receipt_generation", ""), out


def test_vec_v4_012_failed_publication_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-D.3: a failed publication audit names ``audit_failed``."""
    case = _case(tmp_path, "final")
    case.audit["publication_audit"]["result"] = "failed"
    out = _run(case, monkeypatch)
    assert out["status"] == "FAIL", out
    assert "audit_failed" in out["failures"].get("publication_audit", ""), out


@pytest.mark.parametrize("result", ["ambiguous", "audit_insufficient"])
def test_vec_v4_013_v4_014_audit_not_passed_names_the_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, result: str
) -> None:
    """AC-D.3: an ambiguous audit and a disabled reflog each fail and name their result."""
    case = _case(tmp_path, "final")
    case.audit["publication_audit"]["result"] = result
    out = _run(case, monkeypatch)
    assert out["status"] == "FAIL", out
    assert result in out["failures"].get("publication_audit", ""), out


def test_vec_v4_015_foreign_movement_reported_not_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-D.3: movement outside the run is reported and the stage still passes."""
    case = _case(tmp_path, "final")
    movement = [{"ref_old": "1" * 40, "ref_new": "2" * 40}]
    case.audit["publication_audit"]["foreign_movement"] = movement
    out = _run(case, monkeypatch)
    _assert_base(out, "final")
    assert out["foreign_movement"] == movement, out


def test_vec_v4_016_commit_exec_false_stage_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-D.3: under ``commit_exec: false`` the commit checks are n/a; the receipt is not."""
    case = _case(tmp_path, "final", commit_exec=False)
    out = _run(case, monkeypatch)
    assert out["status"] == "PASS", out
    for check in ("commit_manifest", "commit_ops", "publication_audit"):
        assert out["checks"][check] == "n/a", (check, out)
    assert out["checks"]["receipt_generation"] == "pass", out
    case.audit["receipt"] = "missing"
    out = _run(case, monkeypatch)
    assert out["status"] == "FAIL", out
    assert out["checks"]["receipt_generation"] == "fail", out
    assert "provisional_mark" in json.dumps(out["failures"]), out


def test_stage_final_for_produce_defers_audit_and_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-D.3: the produce-time call defers the audit and the receipt and never audits."""
    case = _case(tmp_path, "final", commit_exec=False)
    out = _run(case, monkeypatch, for_produce=True)
    assert out["status"] == "PASS", out
    assert out["checks"]["publication_audit"] == "deferred", out
    assert out["checks"]["receipt_generation"] == "deferred", out


B_ROW_BLOCK = (
    "\n### B-H2-2\n\n"
    "Decision: the human holds the live check "
    "([decision](../../../../.agent/context/handoffs/fixture-decision.md)).\n"
)


def test_stage_blocked_row_with_open_dependency_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-D.3: a ``[B]`` row whose dependency row is still open fails the pending rows."""
    case = _case(tmp_path, "structural")
    case.marks["H2-2"] = "[B]"
    case.tail = B_ROW_BLOCK
    case.cells["H2-2"] = {"task": "Live check, follow-up in B-H2-2", "depends": "none"}
    case.write()
    out = _run(case, monkeypatch)
    assert out["checks"]["pending_rows"] == "pass", out
    case.cells["H2-2"]["depends"] = "H2-4"
    case.write()
    out = _run(case, monkeypatch)
    assert out["checks"]["pending_rows"] == "fail", out
    assert "H2-4" in out["failures"].get("pending_rows", ""), out


# -- the CLI ------------------------------------------------------------------------------


def _argv(args: Namespace) -> list[str]:
    flags = {
        "plan": "--plan",
        "task": "--task",
        "handoff_template": "--handoff-template",
        "review": "--review",
        "review_state_receipt": "--review-state-receipt",
        "expected_review_mode": "--expected-review-mode",
        "expected_target_plan": "--expected-target-plan",
        "reflection": "--reflection",
        "reflection_template": "--reflection-template",
        "reflection_schema": "--reflection-schema",
        "metrics": "--metrics",
        "known_issues": "--known-issues",
        "known_issues_yaml": "--known-issues-yaml",
        "current_focus": "--current-focus",
        "date": "--date",
        "meu": "--meu",
        "issue": "--issue",
    }
    out: list[str] = []
    for attr, flag in flags.items():
        out += [flag, str(getattr(args, attr))]
    for handoff in args.handoff:
        out += ["--handoff", str(handoff)]
    return out


def _cli(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
) -> tuple[int, str]:
    vca = _vca()
    monkeypatch.setattr("sys.argv", ["validate_closeout_artifacts.py", *argv])
    try:
        code = vca.main()
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
    captured = capsys.readouterr()
    return int(code), captured.out + captured.err


def test_stage_cli_legacy_plan_prints_the_stage_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-D.3: ``--stage structural`` on a legacy plan exits 0 with the stage JSON."""
    case = _case(tmp_path, "structural", legacy=True)
    code, out = _cli(monkeypatch, capsys, [*_argv(case.args), "--stage", "structural"])
    assert code == 0, out
    result, _ = json.JSONDecoder().raw_decode(out[out.index("{") :])
    assert (result["status"], result["mode"], result["stage"]) == (
        "PASS",
        "stage",
        "structural",
    ), result


@pytest.mark.parametrize(
    "extra",
    [["--stage", "bogus"], ["--stage", "final", "--full"]],
    ids=["unknown-stage", "stage-with-full"],
)
def test_stage_cli_usage_errors_exit_2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    extra: list[str],
) -> None:
    """AC-D.3: an unknown stage, or ``--stage`` with ``--full``, is a usage error (exit 2)."""
    case = _case(tmp_path, "final", legacy=True)
    code, out = _cli(monkeypatch, capsys, [*_argv(case.args), *extra])
    assert code == 2, out
    vca = _vca()
    assert hasattr(vca, "validate_stage"), "the stage mode does not exist yet"


# -- the final receipt through the run_parameters verbs (AC-D.4, V4-010, V4-011, V4-016 to 018)


def _schema_valid(instance: object) -> None:
    schema = json.loads((SCHEMAS / "final.v1.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate({"final-receipt": instance})


def _rel(plan: str) -> dict[str, str]:
    """The canonical closeout paths of ``plan``, relative to the repository."""
    return {
        "task": f"docs/execution/plans/{plan}/task.md",
        "plan": f"docs/execution/plans/{plan}/implementation-plan.md",
        "handoff": f".agent/context/handoffs/{plan}-handoff.md",
        "review": f".agent/context/handoffs/{plan}-implementation-critical-review.md",
        "reflection": f"docs/execution/reflections/{plan}-reflection.md",
        "metrics": "docs/execution/metrics.md",
        "known_issues": ".agent/context/known-issues.md",
        "known_issues_yaml": ".agent/context/known-issues.yaml",
        "current_focus": ".agent/context/current-focus.md",
    }


METRICS_HEADER = (
    "| Date | MEU(s) | Tool Calls | Time to First Green | Tests Added | Codex Findings "
    "| Handoff Score | Rule Adherence | Prompt→Commit (min) | Notes |\n"
    "|------|--------|------------|---------------------|-------------|----------------"
    "|---------------|----------------|--------------------|-------|\n"
)


def _metrics_row(plan: str) -> str:
    return f"| 2026-10-17 | fixture | 1 | 1 min | 1 | 0 | 7/7 | 100% | 1 | {plan} |\n"


def _complete(fx: bf.Fixture) -> None:
    """Mark the run's carriers closed: both statuses ``complete``, every row ``[x]``."""
    meta, _ = _split(fx.task_path())
    meta["status"] = "complete"
    meta["stop_gate"] = "released:done"
    body = (
        "\n# Task\n\n"
        + TASK_HEADER
        + "".join(
            f"| {row} | task | tester | `artifact` | `command` | none | [x] |\n"
            for row in ROWS
        )
    )
    fx.task_path().write_bytes(_frontmatter(meta, body))
    meta, body = _split(fx.plan_path())
    meta["status"] = "complete"
    fx.plan_path().write_bytes(_frontmatter(meta, body))


def _closeout_files(fx: bf.Fixture) -> dict[str, str]:
    rel = _rel(fx.plan)
    fx.write_text(rel["handoff"], "# Handoff\n\nThe fixture run.\n")
    fx.write_text(rel["review"], "# Review\n\napproved\n")
    fx.write_text(rel["reflection"], "# Reflection\n\nThe fixture run.\n")
    fx.write_text(rel["metrics"], METRICS_HEADER + _metrics_row(fx.plan))
    fx.write_text(rel["known_issues"], "## Active Issues\nNone.\n")
    fx.write_text(rel["known_issues_yaml"], "issues: []\n")
    fx.write_text(rel["current_focus"], "## Status\nThe fixture run.\n")
    return rel


def _flow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> bf.Fixture:
    """A ``commit_exec: false`` run, initialized, bound, closed, with its closeout files."""
    fx = bf.build(tmp_path / "fx", ROOT)
    fx.block = fx.present_and_accept(commit_exec=False)
    fx.write_carrier(fx.block)
    fx.commit("fixture: commit_exec false carriers")
    code, out = fx.run("init", "--plan", fx.plan)
    assert (code, out.get("result")) == (0, "initialized"), out
    for flag in ("--pending", "--plan"):
        code, out = fx.run("bind", flag, fx.plan, "--session", fx.session)
        assert code == 0, out
    _complete(fx)
    _closeout_files(fx)
    monkeypatch.setattr(
        _rp(),
        "run_stage_validators",
        lambda *_a, **_k: copy.deepcopy(VALIDATORS),
        raising=False,
    )
    return fx


def _receipt(fx: bf.Fixture, n: int = 1) -> dict[str, Any]:
    path = fx.store / "final" / fx.plan / f"{n}.json"
    assert path.is_file(), path
    receipt = json.loads(path.read_text(encoding="utf-8"))
    _schema_valid(receipt)
    return dict(receipt)


def _produce(fx: bf.Fixture) -> tuple[int, dict[str, Any]]:
    return fx.run("final", "--produce", "--plan", fx.plan)


def _seal(fx: bf.Fixture) -> tuple[int, dict[str, Any]]:
    return fx.run("final", "--seal", "--plan", fx.plan)


def _status(fx: bf.Fixture) -> dict[str, Any]:
    code, out = fx.run("status", "--plan", fx.plan)
    assert code == 0, out
    return out


def _touch(fx: bf.Fixture, rel: str, extra: str = "A later edit.\n") -> None:
    path = fx.repo / rel
    path.write_bytes(path.read_bytes() + extra.encode("utf-8"))


def test_final_read_set_is_complete_and_classified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-D.4: the read set holds known-issues.md, the review and the handoff; review evidence
    is run-owned; the metrics row is a projection; the shared context files are shared."""
    fx = _flow(tmp_path, monkeypatch)
    rel = _rel(fx.plan)
    entries = {e["path"]: e for e in _rp().final_read_set(fx.repo, fx.plan)}
    for key in ("task", "plan", "handoff", "review", "reflection"):
        assert entries[rel[key]]["shared"] is False, (key, entries)
    assert entries[rel["metrics"]]["kind"] == "projection", entries
    assert entries[rel["metrics"]]["shared"] is False, entries
    assert rel["known_issues"] in entries, entries
    for key in ("known_issues_yaml", "current_focus"):
        assert entries[rel[key]]["shared"] is True, (key, entries)


def test_vec_v4_016_commit_exec_false_tree_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-D.3: a ``commit_exec: false`` run gets a tree receipt with no commit, then a seal."""
    fx = _flow(tmp_path, monkeypatch)
    code, out = _produce(fx)
    assert code == 0, out
    receipt = _receipt(fx)
    assert (
        receipt["generation"],
        receipt["mode"],
        receipt["op"],
        receipt["commit"],
        receipt["predecessor"],
        receipt["sealed"],
        receipt["seal"],
    ) == (1, "tree", "none", "none", "none", False, "none"), receipt
    assert _rel(fx.plan)["handoff"] in {e["path"] for e in receipt["read_set"]}, receipt
    code, out = _seal(fx)
    assert code == 0, out
    receipt = _receipt(fx)
    assert receipt["sealed"] is True, receipt
    assert receipt["seal"]["path"] == f"final/{fx.plan}/1.seal", receipt
    status = _status(fx)
    assert (
        status["done"],
        status["reasons"],
        status["generation_state"],
        status["kind"],
    ) == (True, [], "current", "grant"), status
    code, out = fx.run("final", "--plan", fx.plan)
    assert code == 0 and out["generations"] == [{"generation": 1, "sealed": True}], out


def test_vec_v4_010_snapshot_differs_from_tree_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-D.3: a tree that changes while the validators read the snapshot refuses the receipt."""
    fx = _flow(tmp_path, monkeypatch)
    handoff = _rel(fx.plan)["handoff"]

    def validators(*_a: object, **_k: object) -> dict[str, Any]:
        _touch(fx, handoff)
        return copy.deepcopy(VALIDATORS)

    monkeypatch.setattr(_rp(), "run_stage_validators", validators, raising=False)
    code, out = _produce(fx)
    assert code == 1, out
    assert out.get("reason") == "snapshot_differs", out
    folder = fx.store / "final" / fx.plan
    assert (folder / "1.failed.json").is_file(), sorted(folder.iterdir())
    assert not (folder / "1.json").exists()
    code, out = fx.run("final", "--plan", fx.plan)
    assert code == 0 and out["generations"] == [], out


def test_vec_v4_011_shared_change_keeps_the_receipt_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-D.3: a later change to a shared file keeps the receipt; a run-owned one stales it."""
    fx = _flow(tmp_path, monkeypatch)
    assert _produce(fx)[0] == 0
    assert _seal(fx)[0] == 0
    rel = _rel(fx.plan)
    _touch(fx, rel["known_issues_yaml"], "# another plan's issue\n")
    status = _status(fx)
    assert status["done"] is True, status
    _touch(fx, rel["handoff"])
    status = _status(fx)
    assert status["done"] is False, status
    assert "stale_generation" in status["reasons"], status


def test_final_seal_refused_after_known_issues_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-D.4: a change to known-issues.md between produce and seal refuses the seal."""
    fx = _flow(tmp_path, monkeypatch)
    assert _produce(fx)[0] == 0
    _touch(fx, _rel(fx.plan)["known_issues"])
    code, out = _seal(fx)
    assert code == 1, out
    assert _receipt(fx)["sealed"] is False


def test_final_seal_ignores_another_plans_metrics_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-D.4: the metrics row is projected, so another plan's row does not refuse the seal."""
    fx = _flow(tmp_path, monkeypatch)
    assert _produce(fx)[0] == 0
    _touch(fx, _rel(fx.plan)["metrics"], _metrics_row(bf.PLAN_B))
    code, out = _seal(fx)
    assert code == 0, out
    assert _receipt(fx)["sealed"] is True


def test_vec_v4_017_manual_completion_is_legacy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-D.3: a manual plan is classified legacy and gets no final receipt."""
    fx = bf.build(tmp_path / "fx", ROOT)
    fx.write_carrier({**fx.block, "authorization": {"schema": "manual"}})
    monkeypatch.setattr(
        _rp(), "run_stage_validators", lambda *_a, **_k: VALIDATORS, raising=False
    )
    assert _status(fx)["kind"] == "legacy"
    code, out = _produce(fx)
    assert code == 1 and out.get("reason") == "legacy", out
    assert not (fx.store / "final" / fx.plan / "1.json").exists()


def test_vec_v4_018_authorized_repair_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-D.3: a sealed generation is final; a ``finalize`` grant that supersedes the run's
    authorization opens generation 2, whose receipt names generation 1 as ``predecessor``."""
    fx = _flow(tmp_path, monkeypatch)
    assert _produce(fx)[0] == 0
    assert _seal(fx)[0] == 0
    code, out = _produce(fx)
    assert code == 1, out
    newer = fx.present_and_accept(
        grants=["finalize"],
        supersedes=str(fx.block["authorization"]["message_uuid"]),
        commit_exec=False,
    )
    code, out = fx.run("init", "--block", str(fx.write_block_file(newer, "repair")))
    assert code == 0, out
    code, out = fx.run("repair", "--final", "--plan", fx.plan)
    assert code == 0, out
    assert (out.get("result"), out.get("generation"), out.get("predecessor")) == (
        "repaired",
        2,
        1,
    ), out
    code, out = _produce(fx)
    assert code == 0, out
    receipt = _receipt(fx, 2)
    assert (receipt["generation"], receipt["predecessor"]) == (2, 1), receipt


# -- the publication audit on a real repository (V4-012 to V4-015) ------------------------


def _published(tmp_path: Path) -> tuple[bf.Fixture, list[dict[str, str]], str]:
    """A fixture whose ``main`` moved once by a run op; returns the op and the old tip."""
    fx = bf.build(tmp_path / "fx", ROOT)
    old = bf.git(fx.repo, "rev-parse", "HEAD")
    fx.write_text("docs/published.md", "# Published\n")
    fx.commit("fixture: the run's commit")
    new = bf.git(fx.repo, "rev-parse", "HEAD")
    return fx, [{"op": "op-exec", "ref_old": old, "ref_new": new}], old


def _audit(fx: bf.Fixture, publications: list[dict[str, str]]) -> dict[str, Any]:
    return dict(_rp().publication_audit(fx.repo, "main", publications))


def test_vec_v4_015_publication_audit_passes_and_reports_foreign_movement(
    tmp_path: Path,
) -> None:
    """AC-D.3: the run's update in the reflog passes; a later outside commit is reported."""
    fx, pubs, _ = _published(tmp_path)
    out = _audit(fx, pubs)
    assert (out["result"], out["foreign_movement"]) == ("passed", []), out
    fx.write_text("docs/foreign.md", "# Foreign\n")
    fx.commit("fixture: an outside commit")
    out = _audit(fx, pubs)
    assert out["result"] == "passed", out
    assert out["foreign_movement"], out


def test_vec_v4_013_reversal_is_ambiguous_not_foreign(tmp_path: Path) -> None:
    """AC-D.3: a tip moved back behind the publication is ambiguous, not foreign movement."""
    fx, pubs, old = _published(tmp_path)
    bf.git(fx.repo, "update-ref", "refs/heads/main", old)
    out = _audit(fx, pubs)
    assert (out["result"], out["foreign_movement"]) == ("ambiguous", []), out


def test_vec_v4_014_disabled_reflog_is_audit_insufficient(tmp_path: Path) -> None:
    """AC-D.3: with the reflog disabled and gone, the audit cannot pass: audit_insufficient."""
    fx, pubs, _ = _published(tmp_path)
    bf.git(fx.repo, "config", "core.logAllRefUpdates", "false")
    log = fx.common_dir / "logs" / "refs" / "heads" / "main"
    assert log.is_file(), log
    log.unlink()
    assert _audit(fx, pubs)["result"] == "audit_insufficient"


def test_vec_v4_012_publication_never_on_the_branch_fails(tmp_path: Path) -> None:
    """AC-D.3: a publication the branch never held (an orphan commit) fails the audit."""
    fx, pubs, old = _published(tmp_path)
    tree = bf.git(fx.repo, "rev-parse", "HEAD^{tree}")
    orphan = bf.git(fx.repo, "commit-tree", tree, "-m", "fixture: never published")
    out = _audit(fx, [{"op": "op-exec", "ref_old": old, "ref_new": orphan}])
    assert out["result"] == "failed", out
