---
date: "2026-09-19"
project: "2026-09-19-create-plan-adopter-path-fix"
meu: "MEU-1"
status: "complete"
action_required: "VALIDATE_AND_APPROVE"
template_version: "2.1"
verbosity: "standard"
plan_source: "docs/execution/plans/2026-09-19-create-plan-adopter-path-fix/implementation-plan.md"
build_plan_section: "mock-deploy findings 2.5/2.6/2.9/2.12/2.13/2.16 (create-plan.md only)"
agent: "cursor-grok-4.6"
reviewer: "gpt-5.6-sol"
predecessor: "none"
---

# Handoff: 2026-09-19-create-plan-adopter-path-fix-MEU-1-handoff

> **Status**: `complete`
> **Action Required**: `VALIDATE_AND_APPROVE`

---

## Scope

**MEU**: MEU-1 — Align `core/.agent/workflows/create-plan.md` with the tree ADOPTION-GUIDE copies.
**Build Plan Section**: mock-deploy findings that live in `create-plan.md` only (no `docs/BUILD_PLAN.md` in this origin package).
**Predecessor**: none

Human `proceed` after independent plan-critical-review `approved` (loop `create-plan-adopter-path-fix-plan`, gpt-5.6-sol high, 3 rounds). Product edit is this one file.

---

## Acceptance Criteria

| AC | Type | Description | Source | Test(s) | Status |
|----|------|-------------|--------|---------|--------|
| AC-1 | unit | Step 4 template pre-flight and file:// links name `.agent/templates/PLAN-TEMPLATE.md` and `TASK-TEMPLATE.md` | Spec | Rows 3a+3b | ✅ |
| AC-2 | unit | §5a dispatch prompt names `.agent/templates/REVIEW-TEMPLATE.md` | Spec | Rows 3a+3b | ✅ |
| AC-3 | unit | Step 2 reads D3 (`docs/BUILD_PLAN.md` default); unguarded `cat docs/build-plan/build-priority-matrix.md` absent | Spec | Row 3d | ✅ |
| AC-4 | unit | Batch-invariant / MEU-gate text does not require `validate_codebase.py` unless that file exists | Spec | Row 3c | ✅ |
| AC-5 | unit | Prerequisites list `PROJECT-PROFILE.md` first; missing `current-focus.md` writes a stub | Spec | Row 3e | ✅ |
| AC-6 | unit | Discovery, plan-review read-back, OpenAPI (if shipped), and stamp examples contain no FORBIDDEN_CREATE_PLAN_FORMS | Spec | Row 3a | ✅ |
| AC-7 | unit | Graphify/Headroom absence = `not_applicable` without waiting; GUI §4A skips when named files are absent | Spec | Rows 3f+3g | ✅ |
| AC-8 | unit | PROFILE-forbidden dispatch stops for B4 human; that stop is not SIGN 1; self-review forbidden | Spec | Row 3h | ✅ |
| AC-9 | unit | OpenAPI and session-digest are skip-with-basis when unshipped; MEU gate is D6 from PROFILE | Spec | Row 3i | ✅ |

<!-- CACHE BOUNDARY -->

---

## Evidence

Docs-only MEU. Oracles are fail-closed Python membership tests in `task.md` rows 3a–3i. Pre-edit failure of those oracles was established in plan-critical-review rounds 1–2 (forbidden forms still on disk; unguarded `cat docs/build-plan/build-priority-matrix.md` present). This session ran the same oracles against the edited file.

### FAIL_TO_PASS

| Test | Red Output (hash/snippet) | Green Output | File:Line |
|------|--------------------------|--------------|-----------|
| 3a FORBIDDEN_CREATE_PLAN_FORMS absent | Plan-review R1: `rtk proxy` / origin PLAN-TEMPLATE / `handoffs/REVIEW-TEMPLATE` present | exit 0 (`C:/Temp/agentic-framework/receipts/ac-forbidden.txt`) | create-plan.md discovery/5a/5b/6/8 |
| 3b adopted template paths present | Plan-review R1: no `.agent/templates/PLAN-TEMPLATE.md` | exit 0 (`ac-present.txt`) | 163–169, 296 |
| 3c validate_codebase exists-carve-out | Unedited L150 required `--check contract` with no unless/exists | exit 0 (`ac-validate-codebase.txt`); sole hit L145 | 145 |
| 3d unguarded origin cat gone | Unedited Step 2 fenced `cat docs/build-plan/build-priority-matrix.md` | exit 0 (`ac-d3.txt`) | Step 2 prose |
| 3e PROJECT-PROFILE.md prerequisite | Zero `PROJECT-PROFILE` matches in unedited file | exit 0 (`ac-profile.txt`) | 20 |
| 3f Graphify absence without waiting | Eligible-path wait only; no "without waiting" | exit 0 (`ac-graphify.txt`) | 30, 478 |
| 3g GUI skip token | Skip note lacked `gui-refs-not-shipped` | exit 0 (`ac-gui.txt`) | 262 |
| 3h not SIGN 1 carve-out | Step 5 always auto-dispatch; no PROFILE egress carve-out | exit 0 (`ac-egress.txt`) | 238, 277 |
| 3i skip-with-basis | OpenAPI/session-digest were mandatory origin commands | exit 0 (`ac-skip-basis.txt`) | 515, 614, 617 |

### Commands Executed

| Command | Exit Code | Key Output |
|---------|-----------|------------|
| `Test-Path core/.agent/workflows/create-plan.md` | 0 | True (`create-plan-exists.txt`) |
| row 3a python forbidden-forms assertion | 0 | empty stdout |
| row 3b python required-paths assertion | 0 | empty stdout |
| row 3c python validate_codebase carve-out | 0 | empty stdout |
| row 3d python unguarded-cat assertion | 0 | empty stdout |
| row 3e python PROJECT-PROFILE presence | 0 | empty stdout |
| row 3f python not_applicable + without waiting | 0 | empty stdout |
| row 3g python gui-refs-not-shipped | 0 | empty stdout |
| row 3h python `not SIGN 1` | 0 | empty stdout |
| row 3i python skip-with-basis | 0 | empty stdout |
| `Test-Path docs/BUILD_PLAN.md` | 0 | False — hub N/A (`build-plan-hub.txt`) |
| H1-2 forbidden-forms recheck | 0 | empty stdout (`h1-forbidden.txt`) |
| H1-3 no `.agent/context/meu-status.yaml` | 0 | skip (`meu-skip.txt`) |
| H1-4 no `packages/api` | 0 | skip-with-basis (`openapi-skip.txt`) |
| `git diff --stat -- core/.agent/workflows/create-plan.md` | 0 | 38 insertions, 45 deletions |

### Quality Gate Results

```
skip-with-basis: docs-only MEU; PROFILE D6 for this project is rows 3a–3i (static workflow text).
pyright/ruff/pytest: not in contract; packages/ and origin validate_codebase.py unshipped.
anti-placeholder: FORBIDDEN_CREATE_PLAN_FORMS absent (3a/H1-2).
```

---

## Changed Files

| File | Action | Lines | Summary |
|------|--------|-------|---------|
| `core/.agent/workflows/create-plan.md` | modified | 38/45 | Adopted-tree paths, PROFILE/D6 gates, skip tokens, no origin wrappers |

```diff
-1. `AGENTS.md`
-2. `.agent/context/current-focus.md`
+1. `PROJECT-PROFILE.md` (adopting-project root). If it is absent, **stop** ...
+3. `.agent/context/current-focus.md` — if missing, write a <30-line stub ... and continue
```

```diff
-rtk proxy pwsh -NoProfile -Command { rtk proxy uv run python tools/meu_status.py stats; ... }
+python tools/meu_status.py stats *> {{RECEIPTS_DIR}}/create-plan-discovery.txt; ...
```

```diff
-cat docs/build-plan/build-priority-matrix.md
+Read the Spec hub ... default is `docs/BUILD_PLAN.md`. ... origin-optional companions — read them **only if present**.
```

```diff
-- `implementation-plan.md` — start from [`docs/execution/plans/PLAN-TEMPLATE.md`](...)
+- `implementation-plan.md` — start from [`.agent/templates/PLAN-TEMPLATE.md`](...)
-Use template at .agent/context/handoffs/REVIEW-TEMPLATE.md.
+Use template at .agent/templates/REVIEW-TEMPLATE.md.
```

```diff
+**PROFILE egress carve-out:** ... That stop is a human-decision gate, **not SIGN 1**. Self-review remains prohibited
+... record `gui-refs-not-shipped` ...
+OpenAPI / session digest: **skip-with-basis** when unshipped
```

Sister files (`TASK-TEMPLATE.md`, `delegated-plan-creation.md`, `commands.md`) unchanged on purpose (plan Out of Scope).

---

## Codex Validation Report

_Left blank for reviewer agent. Reviewer fills this section during `/execution-critical-review`._

### Recheck Protocol

1. Read Scope + AC table
2. Verify each AC against Evidence section (file:line, not memory)
3. Run all Commands Executed and compare output
4. Run Quality Gate commands independently
5. Record findings below

### Findings

| # | Severity | Finding | File:Line | Recommendation | Status |
|---|----------|---------|-----------|----------------|--------|
| | | _reviewer fills_ | | | |

### Verdict

`{approved | changes_required}` — _reviewer fills_

---

## Corrections Applied (2026-09-19)

**Findings resolved**: 1/1 (F-001 from execution-critical-review round 1)

| # | Finding | Fix Applied | Verification |
|---|---------|-------------|--------------|
| F-001 | Downstream plan-writing and exit criteria hard-required `docs/BUILD_PLAN.md` instead of resolved PROFILE D3 | Step 4 required-plan bullets and exit criteria now target the resolved D3 hub; `docs/BUILD_PLAN.md` remains the default only | Re-run 3a–3i; semantic D3 oracle from review DR-1 |

---

## Deferred Items

None. Plan Out of Scope rows stay out-of-scope (Human-approved create-plan.md-only basis). Origin tree has no `meu-status.yaml`, so nothing was deferred to a MEU-ID.

---

## History

| Event | Date | Agent | Detail |
|-------|------|-------|--------|
| Created | 2026-09-19 | cursor-grok-4.6 | MEU-1 evidence handoff after WP-1/WP-2 |
| Submitted for review | 2026-09-19 | cursor-grok-4.6 | H1-7 execution-critical-review |
