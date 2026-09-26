---
project: "2026-09-19-create-plan-adopter-path-fix"
date: "2026-09-19"
source: ".agent/context/2026-09-19-adopter-mock-deploy-findings.md §2.5, 2.6 (create-plan rows), 2.9, 2.12, 2.13, 2.16/F031"
meus: ["MEU-1"]
status: "draft"
template_version: "2.0"
---

# Implementation Plan: Align create-plan with the adopted tree

> **Project**: `2026-09-19-create-plan-adopter-path-fix`
> **Build Plan Section(s)**: mock-deploy findings that live in `core/.agent/workflows/create-plan.md` only
> **Status**: `draft`

---

## Goal

A consuming agent that copied this package per ADOPTION-GUIDE can follow
`create-plan.md` through plan+task write without guessing paths, origin tools, or
whether Step 5 dispatch is SIGN 1.

The 2026-09-19 mock deploy (`P:/fw-adopt-probe`) showed the workflow still names
pre-rename template locations, the origin `docs/build-plan/` split, an unshipped
D6 gate, `FORBIDDEN_CREATE_PLAN_FORMS` in discovery cells, Graphify as if
required, and GUI/OpenAPI files that MANIFEST excludes. This project edits
**only** `core/.agent/workflows/create-plan.md` (repo-root path; not a
plan-directory-relative link). It does not execute those edits until this plan
is approved and a human says proceed.

## Context Tool Decision

```yaml
context_tool_decision:
  phase: planning
  eligible_tools: []
  decision: not_applicable
  eligibility_basis: "graphify-out/graph.json absent; graphify-out-research/graph.json absent; Headroom not installed. Single markdown workflow file."
  human_message_reference: null
```

## Handoff Set

| Scope | Canonical handoff |
|---|---|
| MEU-1 | `.agent/context/handoffs/2026-09-19-create-plan-adopter-path-fix-MEU-1-handoff.md` |

Rolling review: `.agent/context/handoffs/2026-09-19-create-plan-adopter-path-fix-plan-critical-review.md`.

## Work Packages and Context Lifecycle

| ID | Work | depends_on | context_strategy | durable_outputs |
|---|---|---|---|---|
| WP-1 | Rewrite create-plan.md path/command/gate text per FIC | — | `shared` | `core/.agent/workflows/create-plan.md` |
| WP-2 | Per-AC fail-closed assertions (task rows 3a–3i) | WP-1 | `shared` | `$env:RECEIPTS_DIR/ac-*.txt` |
| WP-3 | H1 handoff + AC-coverage + execution review; H2 reflection/metrics/commit-draft using shipped `core/tools` | WP-2 | `shared` | MEU-1 handoff; implementation-critical-review; reflection |

## User Review Required

- Confirm scope stays **create-plan.md only**. Sister files (`TASK-TEMPLATE.md`,
  `delegated-plan-creation.md`, `commands.md`) still carry the same path bugs; they
  are out of this plan on purpose (Out of Scope).
- Confirm the Step 5 **egress carve-out**: when PROJECT-PROFILE forbids external
  dispatch, stopping for the named human is a human-decision gate, not SIGN 1.
  Self-review remains prohibited.

## Spec Sufficiency

| Behavior / Contract | Source Type | Source | Resolved? | Notes |
|---|---|---|---|---|
| Templates after adopt are `.agent/templates/*-TEMPLATE.md` | Spec | ADOPTION-GUIDE Step 2; findings 2.5, F029, F033 | yes | create-plan Step 4 and §5a prompt must name those paths |
| Spec hub is PROFILE D3, default `docs/BUILD_PLAN.md` | Spec | ADOPTION-GUIDE Step 2 BUILD_PLAN stub; findings 2.6 / F030 | yes | `docs/build-plan/` is origin-optional |
| D6 is PROFILE, not `validate_codebase.py` | Spec | MANIFEST excluded origin gate; findings 2.6 | yes | Call origin script only if `tools/validate_codebase.py` exists |
| PROFILE is a create-plan prerequisite | Spec | ADOPTION-QUESTIONS “every workflow reads this file”; findings 2.12 | yes | Absent profile → stop, run ADOPTION-GUIDE Step 1 |
| Missing `current-focus.md` is not a stop | Spec | findings 2.9 / F028 | yes | Write <30-line stub and continue |
| Zero MEUs: hand-edit YAML then render | Local Canon | session-grouping A4; findings 2.9 / F027 | yes | CLI has no `add` |
| Discovery/review/stamp cells omit FORBIDDEN_CREATE_PLAN_FORMS | Spec | output-evidence-policy no-RTK layer; Source Project 2.4; findings 2.13 / F034 | yes | One-line `python … *> receipt`; see named predicate |
| Graphify/Headroom/GUI indexes: skip if absent | Spec | MANIFEST excluded; findings F036 | yes | `not_applicable` / `gui-refs-not-shipped` |
| OpenAPI / session-digest: skip if unshipped | Spec | MANIFEST planned/excluded tools | yes | Record skip basis |
| Block C/E stop is not SIGN 1 | Spec | findings 2.16/F031; ADOPTION-QUESTIONS C/E | yes | Named human reviewer; no self-review |

No external-input MEU. No named SQL. No census of tables/ports.

## Feature Intent Contract — MEU-1

Align `core/.agent/workflows/create-plan.md` with the tree ADOPTION-GUIDE actually copies.

### Named predicate: FORBIDDEN_CREATE_PLAN_FORMS

Canonical set. Every other mention of these forms in this plan or `task.md` refers
here by name. After WP-1 these literals must be **absent** from
`core/.agent/workflows/create-plan.md` (command fences and template-path lines):

- `docs/execution/plans/PLAN-TEMPLATE`
- `docs/execution/plans/TASK-TEMPLATE`
- `handoffs/REVIEW-TEMPLATE`
- `rtk proxy`
- `uv run`
- `pwsh -NoProfile -Command`

`validate_codebase` is **not** in this set. AC-4 permits it only inside a
do-not-call-unless-the-file-exists sentence. Task row 3c is that assertion.
The python membership tests in rows 3a/3b/3c **are** the executable encoding of
this named predicate, not a second definition.

Required **present** forms after WP-1:

- `.agent/templates/PLAN-TEMPLATE.md`
- `.agent/templates/TASK-TEMPLATE.md`
- `.agent/templates/REVIEW-TEMPLATE.md`

| AC | Type | Description | Source | Test(s) | Status |
|----|------|-------------|--------|---------|--------|
| AC-1 | unit | Step 4 template pre-flight and file:// links name `.agent/templates/PLAN-TEMPLATE.md` and `TASK-TEMPLATE.md`, not origin plan-dir templates | Spec | Rows 3a+3b | ⬜ |
| AC-2 | unit | §5a dispatch prompt names `.agent/templates/REVIEW-TEMPLATE.md` | Spec | Rows 3a+3b | ⬜ |
| AC-3 | unit | Step 2 reads D3 (`docs/BUILD_PLAN.md` default); `docs/build-plan/build-priority-matrix.md` is “only if present” | Spec | Row 3d: unguarded `cat docs/build-plan/build-priority-matrix.md` absent | ⬜ |
| AC-4 | unit | Batch-invariant / MEU-gate text does not require `validate_codebase.py` unless that file exists | Spec | Row 3c | ⬜ |
| AC-5 | unit | Prerequisites list `PROJECT-PROFILE.md` first; missing `current-focus.md` → write stub | Spec | Row 3e | ⬜ |
| AC-6 | unit | Discovery, plan-review read-back, OpenAPI (if shipped), and stamp examples contain no FORBIDDEN_CREATE_PLAN_FORMS | Spec | Row 3a | ⬜ |
| AC-7 | unit | Graphify/Headroom absence = `not_applicable` without waiting; GUI §4A skips when named files are absent | Spec | Rows 3f+3g | ⬜ |
| AC-8 | unit | Step 4/5: if PROFILE dispatch is PROHIBITED, stop for B4 human; that stop is not SIGN 1; self-review forbidden | Spec | Row 3h | ⬜ |
| AC-9 | unit | Exit criteria: OpenAPI and session-digest are skip-with-basis when tools are unshipped; MEU gate is D6 from PROFILE | Spec | Row 3i | ⬜ |

**Control binding (AC-8):** observable = the carve-out paragraph in create-plan.md (static doc control). Call chain = planner reads PROFILE then either dispatches or ends the turn. Negative oracle = a plan that treats “C1 forbids egress” as SIGN 1 and self-reviews fails review.

**Control binding (rows 3a–3i):** each AC has its own receipt under `$env:RECEIPTS_DIR`. Call chain = those tester rows after WP-1. Negative oracle = the same commands against the current unedited `create-plan.md` must exit nonzero (the defects are still on disk). An implementation that only satisfies 3a–3c cannot close 3d–3i.

**Closeout binding (H1-6 → H1-7 → H2):** observable = MEU-1 handoff file, `--ac-coverage-only` receipt, execution-review `--approved-state-only` receipt. Call chain = task H1-6 creates the handoff H1-6 validates; H1-7 is the independent execution-review barrier; H2 records the verdict. Negative oracle = a task that lints/commits without those rows. Tools are shipped `core/tools/*.py`, not origin `rtk`/`uv`/`tools/`. Session-digest is skip-with-basis (AC-9 / unshipped).

## Out of Scope

No `meu-status.yaml` / grouping exists in this origin tree, so nothing can be
`deferred` to a scheduled MEU-ID. Remaining mock-deploy work is therefore
`out-of-scope` of this create-plan.md-only contract (Human-approved scope; cited findings).

| Item | Basis |
|------|--------|
| `TASK-TEMPLATE.md` / `delegated-plan-creation.md` / `development-lifecycle.md` path updates | `out-of-scope` — findings 2.5 remainder; Human-approved this plan edits only `create-plan.md` |
| `instantiate.py` `--root`, A10 registry collision, PS 5.1 BOM | `out-of-scope` — findings 2.1–2.4, 2.7–2.8; not this workflow |
| `commands.md` / quality-gate D6 rewrite | `out-of-scope` — finding 2.6 remainder; not this workflow |
| Shipping `current-focus.md` seed | `out-of-scope` — finding 2.9 seed; this plan only teaches create-plan to tolerate absence |

This plan's own `/plan-critical-review` loop is in-scope for the planner (create-plan Step 5). It is not a MEU and is not listed above.

## Exact files

- Modify: `core/.agent/workflows/create-plan.md`
- Do not modify: ADOPTION-GUIDE, templates, other workflows (except items listed as out-of-scope, which stay untouched)

## Stop conditions

- Stop before editing `create-plan.md` until this plan is independently approved and a human says proceed (`plan_to_exec_gate: human`).
- Do not instantiate the package, do not touch `P:/fw-adopt-probe` except as evidence citations.

## BUILD_PLAN hub

No `docs/BUILD_PLAN.md` in this package. Task row: confirm hub N/A with `Test-Path`.
