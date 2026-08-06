---
description: Canonical multi-role workflow for scoped implementation tasks.
---

# Orchestrated Delivery Workflow

Use this workflow for implementation tasks where code is changed.

## Default Role Sequence

1. `orchestrator` (required)
2. `researcher` (conditionally required when requirements are unclear, the build plan is under-specified, or current best-practice confirmation is needed)
3. `coder` (required)
4. `tester` (required)
5. `reviewer` (required)
6. `guardrail` (optional, required for high-risk changes)
7. Human approval gate (required before merge/release/deploy)

## High-Risk Triggers (Require Guardrail)

- Encryption or key-management changes
- Authentication/authorization changes
- Migration scripts or schema changes
- File deletion, destructive rewrite, or irreversible operations
- Changes to backup/restore or data export/import integrity

## Task Lifecycle

1. Intake and scope (orchestrator): scope to the approved project plan.
2. Research if needed (researcher): run `.agent/workflows/pre-build-research.md` when the contract is incomplete or current best practice must be confirmed.
3. Implement (coder): complete changes to satisfy the requested behavior and the resolved contract.
4. Validate (tester): execute blocking checks for touched areas.
5. Adversarial review (reviewer): findings-first report with severity.
6. Safety gate (guardrail when triggered): block or clear with notes.
7. Human approval gate: explicit approval required for merge/release/deploy.

## Evidence-First Completion Protocol

A task **cannot** be marked `done` without an attached evidence bundle. Narrative status alone cannot close a task.

**Evidence bundle must include:**

| Field | Required? | Description |
|---|---|---|
| Changed files | Yes | List of every file modified, created, or deleted |
| Commands executed | Yes | Every command run during implementation and testing |
| Test/eval results | Yes | Pass/fail matrix with command output or log references |
| Artifact references | Yes | Links to handoff file, logs, reports, screenshots |
| Reviewer verdict | Yes | Independent reviewer `approved` or `changes_required` |

## No-Deferral Without Replan

If implementation is blocked or incomplete, the task status becomes `blocked`, **never** `done`.

**Rules:**

1. Blocked work must create a **replacement scoped task** with: `owner_role`, `deliverable`, `validation`, `status`.
2. The following are **banned** in completed tasks:
   - `TODO` / `FIXME` comments
   - `NotImplementedError` / `raise NotImplementedError`
   - Empty `except` / `catch` blocks
   - `pass  # placeholder` or `...  # placeholder`
   - Skeleton stubs with no implementation
3. If any banned pattern is found, the task must revert to `in_progress` or `blocked`.
4. Under-specified requirements must be resolved via local docs and targeted research before coding. They are not justification for TODOs, silent narrowing, or implicit future work.

## Handoff Artifact

Create one handoff file per MEU:

`.agent/context/handoffs/{YYYY-MM-DD}-{project-slug}-handoff.md`

Use `.agent/context/handoffs/TEMPLATE.md`.

## Completion Criteria

1. Required roles are executed in sequence.
2. Blocking checks are green.
3. Evidence bundle is attached and complete (see Evidence-First Completion Protocol).
4. No banned placeholders remain in deliverables (see No-Deferral Without Replan).
5. Review verdict is `approved` with no unresolved blockers.
6. Human approval gate is satisfied for merge/release/deploy.
