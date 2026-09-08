#!/usr/bin/env python3
"""Proof-of-failure arms for review-verdict.schema.v2.json.

A schema is a gate, and a gate must be able to fail (verification-principles V4).
These arms exist so the v2 schema's discriminations are *demonstrated* rather than
asserted: every rule v2 adds over v1 has an arm that must be rejected AND an arm
that must be accepted. The must-accept arms are the important half -- a schema that
rejects everything satisfies all the negative arms and is completely broken (V3).

Runs standalone or under pytest:

    python .agent/../tools/tests/test_review_verdict_schema_v2.py
    python tools/tests/test_review_verdict_schema_v2.py
    pytest tools/tests/test_review_verdict_schema_v2.py

Requires ``jsonschema``. If it is absent this exits 3 -- "could not check" is not
"checked and clean" (V5/V31), so it must not be mistaken for a pass.

Exit codes: 0 all arms behaved / 1 at least one arm did not / 3 jsonschema missing.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

#: The schema sits at ``.agent/schemas/`` relative to the repo root; this file at
#: ``tools/tests/``. Resolve from __file__ so the path does not depend on cwd.
SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / ".agent"
    / "schemas"
    / "review-verdict.schema.v2.json"
)


def _base(**overrides):
    """A minimal valid v2 verdict. Overrides replace whole top-level keys."""
    doc = {
        "schema_version": "review-verdict.v2",
        "date": "2026-09-07",
        "review_mode": "plan",
        "loop_id": "plan-example-2026-09-07",
        "round": 1,
        "target_plan": "docs/execution/plans/example.md",
        "agent": "reviewer-a",
        "requested_verbosity": "standard",
        "verdict": "approved",
        "summary": "No blocking findings.",
        "findings": [],
        "checklist_results": [
            {
                "check": "the reference gate can fail",
                "result": "pass",
                "command": "python scripts/refcheck.py --selftest",
                "exit_code": 0,
                "evidence": "4 arm(s), 0 failure(s)",
            }
        ],
    }
    doc.update(overrides)
    return doc


def _finding(**overrides):
    f = {
        "id": "F1",
        "severity": "High",
        "confidence": "High",
        "blocking": True,
        "subject": "deliverable",
        "finding_kind": "behavior",
        "finding": "Totals exclude the final partial row.",
        "file_line": "src/report.py:118",
        "recommendation": "Include the partial row; add a fixture with one.",
        "status": "open",
    }
    f.update(overrides)
    return f


def _without(doc, key):
    out = copy.deepcopy(doc)
    out.pop(key)
    return out


#: (label, document, must_validate)
ARMS = [
    # --- must ACCEPT. Without these the negative arms prove nothing. ---
    ("approved-clean", _base(), True),
    ("approved-with-nonblocking-finding", _base(findings=[_finding(blocking=False)]), True),
    (
        "changes_required-with-blocking",
        _base(verdict="changes_required", findings=[_finding(blocking=True)]),
        True,
    ),
    (
        "control-defeat-with-mechanism",
        _base(
            verdict="changes_required",
            findings=[
                _finding(finding_kind="control-defeat", mechanism="unrun-validation-row")
            ],
        ),
        True,
    ),
    (
        "scaffolding-subject-allowed",
        _base(findings=[_finding(blocking=False, subject="review-scaffolding")]),
        True,
    ),
    (
        "na-row-needs-no-command",
        _base(checklist_results=[{"check": "c", "result": "n/a", "evidence": "not applicable"}]),
        True,
    ),
    ("discovery-mode-allowed", _base(review_mode="discovery"), True),
    # --- must REJECT: the v1 conflation v2 exists to undo ---
    (
        "approved-with-blocking-finding",
        _base(findings=[_finding(blocking=True)]),
        False,
    ),
    (
        "changes_required-nonblocking-only",
        _base(verdict="changes_required", findings=[_finding(blocking=False)]),
        False,
    ),
    ("changes_required-no-findings", _base(verdict="changes_required", findings=[]), False),
    # --- must REJECT: mechanism-class counting (V25/V30/V41) needs a slug ---
    (
        "control-defeat-without-mechanism",
        _base(verdict="changes_required", findings=[_finding(finding_kind="control-defeat")]),
        False,
    ),
    (
        "mechanism-slug-not-kebab",
        _base(
            verdict="changes_required",
            findings=[_finding(finding_kind="control-defeat", mechanism="Unrun_Validation")],
        ),
        False,
    ),
    # --- must REJECT: V43 subject classification must be one of the three ---
    ("subject-freeform", _base(findings=[_finding(blocking=False, subject="the-vibes")]), False),
    # --- must REJECT: V4 -- an asserted outcome with no command behind it ---
    (
        "pass-row-without-command",
        _base(checklist_results=[{"check": "c", "result": "pass", "evidence": "looked fine"}]),
        False,
    ),
    (
        "approved-with-failing-checklist-row",
        _base(
            checklist_results=[
                {"check": "c", "result": "fail", "command": "x", "evidence": "e"}
            ]
        ),
        False,
    ),
    # --- must REJECT: ledger keys (V41) are not optional ---
    ("missing-loop_id", _without(_base(), "loop_id"), False),
    ("missing-round", _without(_base(), "round"), False),
    ("round-zero", _base(round=0), False),
    # --- must REJECT: structural ---
    ("extra-toplevel-key", _base(vibe="good"), False),
    (
        "finding-missing-blocking",
        _base(
            verdict="changes_required",
            findings=[_without(_finding(), "blocking")],
        ),
        False,
    ),
    # --- must REJECT: a v1 document submitted to a v2-registered loop ---
    (
        "v1-document-refused-by-v2",
        {
            "schema_version": "review-verdict.v1",
            "date": "2026-09-07",
            "review_mode": "plan",
            "target_plan": "p",
            "agent": "a",
            "requested_verbosity": "standard",
            "verdict": "approved",
            "summary": "s",
            "findings": [],
            "checklist_results": [{"check": "c", "result": "pass", "evidence": "e"}],
        },
        False,
    ),
]


def run() -> int:
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        sys.stderr.write(
            "UNAVAILABLE: jsonschema is not installed, so the v2 schema arms did not "
            "run. This is exit 3, not a pass: an unrun gate is not a clean gate "
            "(verification-principles V5). Install with: pip install jsonschema\n"
        )
        return 3

    if not SCHEMA_PATH.is_file():
        sys.stderr.write(f"UNAVAILABLE: schema not found at {SCHEMA_PATH}\n")
        return 3

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)

    failures = 0
    accepted = rejected = 0
    for label, doc, must_validate in ARMS:
        errors = list(validator.iter_errors(doc))
        validated = not errors
        if validated:
            accepted += 1
        else:
            rejected += 1
        if validated == must_validate:
            print(f"PASS {label:<38} {'accepted' if validated else 'rejected'}")
        else:
            failures += 1
            want = "accepted" if must_validate else "rejected"
            print(f"FAIL {label:<38} expected {want}")
            for err in errors[:2]:
                print(f"       {err.message[:120]}")

    # A schema that rejects every document satisfies every negative arm. Say the
    # split out loud so a reader can see both halves were exercised.
    print(f"\nRESULT: {len(ARMS)} arm(s), {failures} failure(s) "
          f"[{accepted} accepted, {rejected} rejected]")
    return 1 if failures else 0


def test_review_verdict_schema_v2_arms():
    """pytest entry point."""
    assert run() == 0


if __name__ == "__main__":
    raise SystemExit(run())
