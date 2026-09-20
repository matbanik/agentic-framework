---
date: "2026-09-19"
review_mode: "execution"
target_plan: "docs/execution/plans/2026-09-19-create-plan-adopter-path-fix/implementation-plan.md"
verdict: "approved"
findings_count: 0
template_version: "2.1"
requested_verbosity: "standard"
agent: "gpt-5.6-sol"
---

# Critical Review: create-plan-adopter-path-fix

> **Review Mode**: `execution`
> **Verdict**: `approved`

---

## Intent Anchor

MEU-1 was supposed to let an adopting agent follow `create-plan.md` through plan and task creation using the adopted template tree, PROFILE-selected D3/D6 controls, explicit optional-tool skips, and the correct human-review stop when external dispatch is forbidden. The delivered workflow satisfies the named literal/path predicates and egress carve-out, but it does not fully achieve that intent because downstream plan-writing and closeout instructions override a non-default PROFILE D3 hub with `docs/BUILD_PLAN.md`.

## Scope

**Target**: `core/.agent/workflows/create-plan.md`; correlated plan/task and MEU-1 handoff under `2026-09-19-create-plan-adopter-path-fix`
**Review Type**: execution review of one docs-only MEU
**Correlation**: the plan, task, and handoff share the exact date/slug and name MEU-1 as the sole handoff; no sibling MEU expansion applies.
**Checklist Applied**: IR-7 and DR-1–DR-8; IR-1–IR-6 are N/A because the contract is static workflow text with no runtime IR.

---

## Findings

| # | Severity | Blocking | Kind | Finding | File:Line | Recommendation | Status |
|---|----------|----------|------|---------|-----------|----------------|--------|
| F-001 | High | yes | behavior | AC-3 was only implemented in Step 2. The plan-writing contract required an explicit `docs/BUILD_PLAN.md` task, and the exit criteria required regenerating that same path. `PROJECT-PROFILE.md` permits D3 to name another canonical source, and ADOPTION-GUIDE copies the stub to that D3 path. Concrete failure: with D3=`docs/SPEC.md` and no `docs/BUILD_PLAN.md`, the workflow first resolved `docs/SPEC.md`, then forced the planner to invent or operate on a nonexistent default hub. This violated AC-3 and the goal that adopters reach plan+task write without guessing paths. | `core/.agent/workflows/create-plan.md:216` (also 230, 613; D3 contract: `PROJECT-PROFILE-TEMPLATE.md:69`, `ADOPTION-GUIDE.md:54`) | Replace all downstream hard-coded hub requirements with the resolved PROFILE D3 path, retaining `docs/BUILD_PLAN.md` only as the default and preserving the documented N/A branch where applicable. | fixed |

---

## Checklist Results

### Information Retrieval (IR)

| Check | Result | Command | Exit | Evidence |
|-------|--------|---------|------|----------|
| IR-1–IR-6 runtime checks | n/a | — | — | Docs-only static workflow contract; no runtime IR was introduced. |
| IR-7 AC coverage | pass | `rtk read C:/Temp/agentic-framework/receipts/handoff-ac-check.txt` | 0 | Receipt says all 9 plan ACs are present in the handoff. No deferred MEU or integration-type AC exists. |

### Design Review (DR)

| Check | Result | Command | Exit | Evidence |
|-------|--------|---------|------|----------|
| DR-1 Claim-to-state match | fail | `rtk python -X utf8 -c "import pathlib,sys; lines=pathlib.Path('core/.agent/workflows/create-plan.md').read_text(encoding='utf-8').splitlines(); hits=[f'{i+1}:{line}' for i,line in enumerate(lines) if 'docs/BUILD_PLAN.md' in line and ('An explicit task to review and update' in line or 'specifically, do not use vague wording' in line or 'status regions regenerated' in line)]; print(*hits,sep='\\n'); sys.exit(1 if hits else 0)"` | 1 | Live hits at 216, 230, and 613 contradict the handoff's claim that AC-3 is complete for the PROFILE D3 hub. |
| DR-2 Residual forbidden forms | pass | `rtk python -c "import pathlib,sys; t=pathlib.Path('core/.agent/workflows/create-plan.md').read_text(encoding='utf-8'); bad=('docs/execution/plans/PLAN-TEMPLATE','docs/execution/plans/TASK-TEMPLATE','handoffs/REVIEW-TEMPLATE','rtk proxy','uv run','pwsh -NoProfile -Command'); sys.exit(1 if any(x in t for x in bad) else 0)"` | 0 | Row 3a live rerun found no FORBIDDEN_CREATE_PLAN_FORMS literal. |
| DR-3 Downstream references updated | fail | `rtk rg -n "PROFILE D3|docs/BUILD_PLAN.md" core/.agent/workflows/create-plan.md` | 0 | Step 2 is PROFILE-driven at 56/60, but downstream mandatory instructions remain fixed to the default at 216/230/613. |
| DR-4 Verification robustness | partial | `rtk rg -n "AC-3|Row 3d|ac-d3" docs/execution/plans/2026-09-19-create-plan-adopter-path-fix .agent/context/handoffs/2026-09-19-create-plan-adopter-path-fix-MEU-1-handoff.md` | 0 | AC-3's oracle checks only removal of the old unguarded `cat`; it cannot detect downstream hard-coding of the default hub. |
| DR-5 Evidence auditability | pass | `rtk read C:/Temp/agentic-framework/receipts/handoff-check.txt` | 0 | Validator receipt is complete and reports 9 AC rows, bound plan_source, all ACs present, and no blocked rows. |
| DR-6 Cross-reference integrity | fail | `rtk rg -n "D3|docs/BUILD_PLAN.md" PROJECT-PROFILE-TEMPLATE.md ADOPTION-GUIDE.md core/.agent/workflows/create-plan.md` | 0 | PROFILE and adoption canon allow a non-default D3 path; the workflow's downstream fixed path is inconsistent with that canon. |
| DR-7 Evidence freshness | pass | `rtk git diff --stat -- core/.agent/workflows/create-plan.md` | 0 | Live diff remains one file with 38 insertions and 45 deletions, matching the handoff receipt. Mandatory live oracle reruns are recorded below. |
| DR-8 Completion vs residual risk | fail | `rtk rg -n "status: \"complete\"|AC-3|docs/BUILD_PLAN.md" .agent/context/handoffs/2026-09-19-create-plan-adopter-path-fix-MEU-1-handoff.md core/.agent/workflows/create-plan.md` | 0 | The handoff marks the MEU complete and AC-3 green while the downstream D3 contradiction remains. |

### Required Live Oracle Reruns

| Check | Result | Command | Exit | Evidence |
|-------|--------|---------|------|----------|
| Row 3a forbidden-form assertion | pass | `rtk python -c "import pathlib,sys; t=pathlib.Path('core/.agent/workflows/create-plan.md').read_text(encoding='utf-8'); bad=('docs/execution/plans/PLAN-TEMPLATE','docs/execution/plans/TASK-TEMPLATE','handoffs/REVIEW-TEMPLATE','rtk proxy','uv run','pwsh -NoProfile -Command'); sys.exit(1 if any(x in t for x in bad) else 0)"` | 0 | No forbidden literal is present. |
| Row 3c validate_codebase carve-out | pass | `rtk python -c "import pathlib,sys; hits=[ln for ln in pathlib.Path('core/.agent/workflows/create-plan.md').read_text(encoding='utf-8').splitlines() if 'validate_codebase' in ln]; sys.exit(0 if all(('unless' in h or 'exists' in h or 'do not call' in h) for h in hits) else 1)"` | 0 | The live mention is guarded by file existence. |
| Row 3d old unguarded build-plan cat | pass | `rtk python -c "import pathlib,sys; t=pathlib.Path('core/.agent/workflows/create-plan.md').read_text(encoding='utf-8'); sys.exit(1 if 'cat docs/build-plan/build-priority-matrix.md' in t else 0)"` | 0 | The old origin-only command is absent; this does not resolve F-001. |
| Row 3h PROFILE egress carve-out | pass | `rtk python -c "import pathlib,sys; t=pathlib.Path('core/.agent/workflows/create-plan.md').read_text(encoding='utf-8'); sys.exit(0 if 'not SIGN 1' in t else 1)"` | 0 | Live lines 238 and 277 also retain the self-review prohibition. |
| Row 3i unshipped-tool skip basis | pass | `rtk python -c "import pathlib,sys; t=pathlib.Path('core/.agent/workflows/create-plan.md').read_text(encoding='utf-8'); sys.exit(0 if 'skip-with-basis' in t else 1)"` | 0 | OpenAPI and session-digest skip text is present at 515/614/617; D6 is PROFILE-driven at 145/511/514/610. |
| H1-2 forbidden-form recheck | pass | `rtk python -c "import pathlib,sys; t=pathlib.Path('core/.agent/workflows/create-plan.md').read_text(encoding='utf-8'); bad=('docs/execution/plans/PLAN-TEMPLATE','docs/execution/plans/TASK-TEMPLATE','handoffs/REVIEW-TEMPLATE','rtk proxy','uv run','pwsh -NoProfile -Command'); sys.exit(1 if any(x in t for x in bad) else 0)"` | 0 | Independent duplicate rerun also exited 0. |

### Post-Implementation Review (PR)

| Check | Result | Command | Exit | Evidence |
|-------|--------|---------|------|----------|
| Evidence bundle complete | partial | `rtk read .agent/context/handoffs/2026-09-19-create-plan-adopter-path-fix-MEU-1-handoff.md` | 0 | Handoff and receipts exist, but the AC-3 evidence is too narrow to establish the full claim. |
| FAIL_TO_PASS table present | pass | `rtk rg -n "FAIL_TO_PASS|3a|3b|3c|3d|3e|3f|3g|3h|3i" .agent/context/handoffs/2026-09-19-create-plan-adopter-path-fix-MEU-1-handoff.md` | 0 | The handoff records all nine rows and red/green provenance. |
| Commands independently runnable | pass | `rtk python -X utf8 core/tools/meu_status.py --help` | 0 | The local CLI exposes distinct `list`, `next`, and `stats` commands; targeted Python/rg checks also ran directly. |
| Anti-placeholder scan clean | pass | `rtk python -c "import pathlib,sys; t=pathlib.Path('core/.agent/workflows/create-plan.md').read_text(encoding='utf-8'); bad=('docs/execution/plans/PLAN-TEMPLATE','docs/execution/plans/TASK-TEMPLATE','handoffs/REVIEW-TEMPLATE','rtk proxy','uv run','pwsh -NoProfile -Command'); sys.exit(1 if any(x in t for x in bad) else 0)"` | 0 | Named forbidden forms are absent. |

---

## Out-of-Contract Observations

- Sister-file adopter-path defects explicitly excluded by the approved plan were not treated as findings.

## Open Questions / Assumptions

None. `PROJECT-PROFILE-TEMPLATE.md:69` makes D3 configurable, and `ADOPTION-GUIDE.md:54` explicitly permits copying the stub to that non-default path.

## Residual Risk

This is a static docs-only MEU, so IR-1–IR-6 runtime risks are N/A. After F-001 is corrected, the same six required live oracles should be rerun plus a semantic D3-path assertion that covers Step 2, plan generation, and exit criteria together.

---

## Verdict

`changes_required` — the literal/path oracles are honestly green, and the PROFILE egress stop is correctly distinguished from SIGN 1 with self-review prohibited. However, F-001 is a High blocking contract defect: valid non-default D3 adopters are still forced back onto `docs/BUILD_PLAN.md` during plan/task generation and closeout, so the execution does not yet achieve its adopter-path intent.

---

## Corrections Applied (2026-09-19)

**Findings resolved**: 1/1 rechecked

| # | Finding | Fix Applied | Verification |
|---|---------|-------------|--------------|
| F-001 | Downstream hard-coded `docs/BUILD_PLAN.md` hub | Step 4 plan-writing bullets and exit criteria now name the resolved PROFILE D3 hub; default path remains `docs/BUILD_PLAN.md` on separate lines | Oracles 3a–3i plus the reviewer's DR-1 semantic conjunction (must now miss) |

---

## Recheck (2026-09-19)

### Intent Anchor

The delivered `create-plan.md` must carry an adopter through plan and task writing using the PROFILE-selected D3 spec hub, whose default is `docs/BUILD_PLAN.md`, without forcing that default when the profile selects another path. The corrected workflow now achieves that intent across Step 2, Step 4, and the exit criteria.

### Scope

Round 2 rechecked F-001 only against the live `core/.agent/workflows/create-plan.md`, the correction recorded in the MEU-1 handoff, the correlated plan/task, and `C:/Temp/agentic-framework/receipts/ac-recheck-r2.txt`. Sister-file path behavior remains outside the approved contract.

### Findings

No open findings. F-001 is fixed: downstream requirements now name the resolved PROFILE D3 hub, and every surviving `docs/BUILD_PLAN.md` reference is explicitly default-only.

| # | Severity | Blocking | Kind | Finding | File:Line | Recommendation | Status |
|---|----------|----------|------|---------|-----------|----------------|--------|
| F-001 | High | no | behavior | Step 4 and the exit criteria previously forced `docs/BUILD_PLAN.md` instead of the resolved PROFILE D3 hub. The live correction removes that failure. | `core/.agent/workflows/create-plan.md:216` (also 217, 231–232, 615) | No further correction; retain the resolved-D3/default distinction. | fixed |

### Checklist Results

| Check | Result | Command | Exit | Evidence |
|-------|--------|---------|------|----------|
| IR-1–IR-6 runtime checks | n/a | — | — | Docs-only static workflow contract; no runtime implementation or tests are in scope. |
| IR-7 AC/deferral integrity | pass | `rtk read .agent/context/handoffs/2026-09-19-create-plan-adopter-path-fix-MEU-1-handoff.md` | 0 | All nine ACs remain represented; there is no deferred MEU, and sister-file exclusions retain their approved basis. |
| DR-1 F-001 semantic conjunction | pass | exact round-1 Python conjunction over `docs/BUILD_PLAN.md` plus the three formerly mandatory phrases | 0 | No hits. The exact command that exited 1 in round 1 now exits 0 against the live file. |
| DR-2 residual default references | pass | `rtk grep -n "docs/BUILD_PLAN\\.md|PROFILE D3|Resolved PROFILE D3" core/.agent/workflows/create-plan.md` | 0 | The four `docs/BUILD_PLAN.md` hits are at 56, 60, 217, and 232; each identifies it only as the D3 default. |
| DR-3 downstream path propagation | pass | targeted live read of `create-plan.md:211–234` and `create-plan.md:609–620` | 0 | Lines 216–217 and 231–232 require the resolved D3 hub and forbid inventing the default; line 615 carries the resolved D3 hub into exit criteria. |
| DR-4 verification robustness | pass | `rtk read C:/Temp/agentic-framework/receipts/ac-recheck-r2.txt` | 0 | The correction receipt includes 3a–3i plus the reviewer-authored semantic conjunction, with all exits recorded. |
| DR-5 evidence auditability | pass | exact DR-1 rerun plus receipt read | 0 | The target, predicate, output, and exit status are reproducible and agree. |
| DR-6 cross-reference integrity | pass | `rtk grep -n "D3|Spec hub" PROJECT-PROFILE-TEMPLATE.md ADOPTION-GUIDE.md` | 0 | The workflow now preserves PROFILE D3 as the selected source rather than creating a second default hub. |
| DR-7 evidence freshness | pass | exact DR-1 rerun against the live file | 0 | Live no-hit output matches the round-2 receipt. |
| DR-8 completion vs residual risk | pass | live corrected-surface read | 0 | No known D3-path gap survives, so the completion claim no longer conflicts with current state. |

### Commands Executed

| Command | Exit | Key Output |
|---------|------|------------|
| Exact round-1 DR-1 Python conjunction | 0 | No hits |
| `rtk read C:/Temp/agentic-framework/receipts/ac-recheck-r2.txt` | 0 | 3a–3i exit 0; DR-1 no hits / exit 0; `ALL_OK` |
| `rtk grep -n "docs/BUILD_PLAN\\.md|PROFILE D3|Resolved PROFILE D3" core/.agent/workflows/create-plan.md` | 0 | D3 semantics at lines 56, 60, 216–217, 231–232, and 615 |
| Targeted live line read of Step 2, Step 4, and exit criteria | 0 | Corrected resolved-D3 wording present |

### Open Questions / Assumptions

None.

### Residual Risk

The original AC-3 row-3d oracle remains narrower than the full D3 propagation requirement, but the round-2 correction receipt and independent DR-1 conjunction directly cover the previously missed downstream failure. No new material failure was found on this surface.

### Verdict

`approved` — F-001 is fixed. Adopted `create-plan.md` now carries plan-and-task writing and closeout through the resolved PROFILE D3 hub, using `docs/BUILD_PLAN.md` only as the default and never as a mandatory second hub.
