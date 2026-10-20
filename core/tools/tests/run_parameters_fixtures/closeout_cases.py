"""Closeout cases shared by the run-parameters stage tests (B-4, EA-42 a).

The {{PROJECT_NAME_TITLE}} source holds these in its ``validate_closeout_artifacts`` test module. The
framework has no such module, so the four names the stage tests import
(``SCRATCH_CITATION``, ``VACUOUS_H23_FIXTURE``, ``WRONG_TARGET_PLAN`` and
``_full_closeout_args``) and what they use live here. Test setup only: no test is defined here.

Every artifact is written in the framework's own formats: the review is a REVIEW-TEMPLATE
file whose state receipt ``check_review_state`` writes, the handoff carries an
``evidence.v1`` record and a ``## Decision Log``, and the reflection fills the framework
template's headings and the ``reflection.v1`` schema.
"""

from __future__ import annotations

import importlib
from argparse import Namespace
from pathlib import Path
from typing import Any

from tools.tests.run_parameters_fixtures import build_fixture as bf

TARGET_PLAN = f"docs/execution/plans/{bf.PLAN}/implementation-plan.md"


WRONG_TARGET_PLAN = (
    "docs/execution/plans/2026-07-01-wrong-target/implementation-plan.md"
)

#: The framework's reflection schema, the one the shipped template is checked against.
REFLECTION_SCHEMA = Path(__file__).resolve().parents[3] / ".agent" / "schemas" / "reflection.v1.yaml"

EVIDENCE = (
    '{"schema_version": "evidence.v1", "check_id": "suite", "command": "python -m unittest", '
    '"cwd": ".", "scope": "unit suite", "phase": "targeted", "exit_code": 0, '
    '"result": "pass", "tested_state": "fixture-tree", "output": "12 tests passed"}'
)


def _vca() -> Any:
    return importlib.import_module("tools.validate_closeout_artifacts")


def _approved_review_state(tmp_path: Path) -> tuple[Path, Path, dict[str, Any]]:
    """An approved two-round execution review and the state receipt written from it."""
    vca = _vca()
    review = tmp_path / "review.md"
    review.write_text(
        "---\n"
        "date: 2026-07-14\n"
        "review_mode: execution\n"
        f"target_plan: {TARGET_PLAN}\n"
        "verdict: approved\n"
        "findings_count: 1\n"
        'template_version: "2.1"\n'
        "---\n"
        "\n"
        "# Execution review\n"
        "\n"
        "## Findings\n"
        "\n"
        "| # | Severity | Finding | File:Line | Recommendation | Status |\n"
        "|---|----------|---------|-----------|----------------|--------|\n"
        "| 1 | Low | naming nit | a.py:3 | rename | fixed |\n"
        "\n"
        "## Recheck\n"
        "\n"
        "Round 2: the naming nit is fixed.\n"
        "\n"
        "## Verdict\n"
        "\n"
        "approved\n",
        encoding="utf-8",
    )
    state, _ = vca.check_review_state(
        review.read_text(encoding="utf-8"), str(review), "execution", TARGET_PLAN, 6
    )
    state_path = tmp_path / "state.json"
    vca.write_state(str(state_path), state)
    return review, state_path, state


def _full_closeout_args(tmp_path: Path) -> Namespace:
    review, state_path, state = _approved_review_state(tmp_path)
    plan = tmp_path / "plan.md"
    plan.write_text(
        "| AC | Type |\n|----|------|\n| AC-303-E1 | integration |\n",
        encoding="utf-8",
    )
    task = tmp_path / "task.md"
    statuses = {
        "H1-7": "[x]",
        "H2-1": "[x]",
        "H2-2": "[x]",
        "H2-3": "[x]",
        "H2-4": "[ ]",
        "H2-5": "[ ]",
    }
    task.write_text(
        "\n".join(
            f"| {row} | task | tester | `artifact` | `command` | `{status}` |"
            for row, status in statuses.items()
        ),
        encoding="utf-8",
    )
    handoff_template = tmp_path / "handoff-template.md"
    handoff_template.write_text(
        "## Acceptance Criteria\n"
        "<!-- CACHE BOUNDARY -->\n"
        "## Evidence\n"
        "## Codex Validation Report\n"
        "## Corrections Applied ({YYYY-MM-DD})\n"
        "## Decision Log\n",
        encoding="utf-8",
    )
    handoff = tmp_path / "handoff.md"
    handoff.write_text(
        f"""---
plan_source: "docs/execution/plans/{bf.PLAN}/implementation-plan.md"
---

## Scope
Scope.
## Acceptance Criteria
| AC | Type | Description | Source | Test(s) | Status |
|----|------|-------------|--------|---------|--------|
| AC-303-E1 | integration | Persists | Spec | test_file:test_name | complete |
<!-- CACHE BOUNDARY -->
## Evidence

```json
{EVIDENCE}
```

## Changed Files
| File | Action | Lines | Summary |
|------|--------|-------|---------|
| `tool.py` | modified | 1-5 | Validates structure |
## Codex Validation Report
{review}
{state["verdict"]}
2026-07-14
{state["rounds"]}
{state["review_digest"]}
## Corrections Applied (2026-07-14)
| Finding | Disposition | Evidence |
|---------|-------------|----------|
| R1-F1 | Fixed the naming nit | 12 tests passed |
## Decision Log

None.
""",
        encoding="utf-8",
    )
    reflection_template = tmp_path / "reflection-template.md"
    reflection_template.write_text(
        "# {YYYY-MM-DD} Meta-Reflection\n"
        "## Execution Trace\n"
        "### Friction Log\n"
        "### Decisions Log\n"
        "## Pattern Extraction\n"
        "## Instruction Coverage\n",
        encoding="utf-8",
    )
    reflection_schema = tmp_path / "reflection-schema.yaml"
    reflection_schema.write_text(REFLECTION_SCHEMA.read_text(encoding="utf-8"), encoding="utf-8")
    reflection = tmp_path / "reflection.md"
    reflection.write_text(
        """# 2026-07-14 Meta-Reflection
## Execution Trace
### Friction Log
Substantive friction.
### Decisions Log
None.
## Pattern Extraction
Substantive pattern.
## Instruction Coverage
```yaml
schema: v1
session:
  id: test-session
  task_class: tdd
  outcome: success
sections:
  - id: execution_contract
    cited: true
    influence: 3
loaded:
  workflows: []
  roles: []
  skills: []
  refs: []
decisive_rules: ["P1:tests-first"]
conflicts: []
note: The validator gate decided the closeout.
slim_candidate: [validator]
review_churn:
  rounds_to_approval: {plan: 0, execution: 2}
  findings_per_round:
    - {round: 1, critical: 0, high: 0, medium: 0, low: 1}
    - {round: 2, critical: 0, high: 0, medium: 0, low: 0}
  churned_findings: 0
  finding_categories: {naming: 1}
  verdicts: {changes_required: 1, approved: 1}
meu_work_classes: [correctness]
```
""",
        encoding="utf-8",
    )
    metrics = tmp_path / "metrics.md"
    metrics.write_text(
        "| Date | MEU(s) | Tool Calls | Time to First Green | Tests Added | Codex Findings | Handoff Score | Rule Adherence | Prompt→Commit (min) | Notes |\n"
        "|------|--------|------------|---------------------|-------------|----------------|---------------|----------------|--------------------|-------|\n"
        "| 2026-07-14 | MEU-303-FU | 20 | 5 min | 10 | 1 low resolved in 2 rounds | 7/7 | 100% | 60 | Complete |\n",
        encoding="utf-8",
    )
    known_issues = tmp_path / "known-issues.md"
    known_issues.write_text(
        "## Active Issues\nOther issue.\n## Mitigated / Workaround\nNone.",
        encoding="utf-8",
    )
    # R3-F1 (2026-08-23, Human-approved): resolution evidence lives in the YAML
    # SSOT, not the frozen legacy known-issues-archive.md.
    known_issues_yaml = tmp_path / "known-issues.yaml"
    known_issues_yaml.write_text(
        "issues:\n"
        "- id: CORE-BALSYNC-NOCOMMIT\n"
        "  status: resolved\n"
        "  resolved: '2026-07-14'\n"
        "  resolution: Balance-sync commit path fixed and regression-tested.\n"
        "  meu_links: [MEU-303-FU]\n",
        encoding="utf-8",
    )
    current_focus = tmp_path / "current-focus.md"
    current_focus.write_text(
        "## Status\n"
        "**Outcome:** approved\n"
        "**Resolved Issue:** `CORE-BALSYNC-NOCOMMIT`\n"
        "**MEU:** `MEU-303-FU`\n",
        encoding="utf-8",
    )
    return Namespace(
        plan=plan,
        task=task,
        handoff=handoff,
        handoff_template=handoff_template,
        review=review,
        review_state_receipt=state_path,
        expected_review_mode="execution",
        expected_target_plan=TARGET_PLAN,
        reflection=reflection,
        reflection_template=reflection_template,
        reflection_schema=reflection_schema,
        metrics=metrics,
        known_issues=known_issues,
        known_issues_yaml=known_issues_yaml,
        known_issues_archive=None,
        grouping=None,
        current_focus=current_focus,
        date="2026-07-14",
        meu="MEU-303-FU",
        issue="CORE-BALSYNC-NOCOMMIT",
    )


VACUOUS_H23_FIXTURE = (
    "rtk proxy pwsh -NoProfile -Command { Get-Content docs/execution/metrics.md "
    "-Tail 3 } *> {{RECEIPTS_DIR}}/metrics-check.txt; $code=$LASTEXITCODE; "
    "Get-Content {{RECEIPTS_DIR}}/metrics-check.txt; exit $code"
)


SCRATCH_CITATION = "{{RECEIPTS_DIR}}/gate.txt"
