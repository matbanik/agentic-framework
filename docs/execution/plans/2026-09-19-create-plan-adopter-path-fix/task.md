---
project: "2026-09-19-create-plan-adopter-path-fix"
source: "docs/execution/plans/2026-09-19-create-plan-adopter-path-fix/implementation-plan.md"
meus: ["MEU-1"]
status: "in_progress"
template_version: "2.1"
---

# Task — Align create-plan with the adopted tree

> **Project:** `2026-09-19-create-plan-adopter-path-fix`
> **Type:** Docs
> **Estimate:** 1 production file after approval

## Context Tool Decision

```yaml
context_tool_decision:
  phase: planning
  eligible_tools: []
  decision: not_applicable
  eligibility_basis: "graphify-out/graph.json absent; Headroom not installed; one markdown workflow."
  human_message_reference: null
```

Handoff set: `.agent/context/handoffs/2026-09-19-create-plan-adopter-path-fix-MEU-1-handoff.md` (created at H1-6, not before).

Receipts: `$env:RECEIPTS_DIR` (session value `C:/Temp/agentic-framework/receipts`).
FORBIDDEN_CREATE_PLAN_FORMS is defined in the implementation plan; rows 3a–3c are its executable encoding.

Do not edit `create-plan.md` until a human says proceed after this plan is independently approved.

| # | Task | Owner | Deliverable | Validation | Depends on | Context strategy | Durable outputs | builder_model | Status |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Re-read FIC AC-1–AC-9 in the implementation plan | coder | Source-read of ACs | `view_file: docs/execution/plans/2026-09-19-create-plan-adopter-path-fix/implementation-plan.md` | — | shared | implementation-plan.md | `coordinator` | `[x]` |
| 2 | Present this plan; do not edit create-plan.md until human says proceed | orchestrator | Draft on disk; turn ends | `Test-Path docs/execution/plans/2026-09-19-create-plan-adopter-path-fix/implementation-plan.md *> $env:RECEIPTS_DIR/plan-exists.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/plan-exists.txt; exit $code` | 1 | shared | C:/Temp/agentic-framework/receipts/plan-exists.txt | `coordinator` | `[x]` |
| 3 | After approval: edit create-plan.md to satisfy AC-1–AC-9 | coder | Updated workflow | `Test-Path core/.agent/workflows/create-plan.md *> $env:RECEIPTS_DIR/create-plan-exists.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/create-plan-exists.txt; exit $code` | 2 | shared | core/.agent/workflows/create-plan.md | `coordinator` | `[x]` |
| 3a | AC-1/2/6: FORBIDDEN_CREATE_PLAN_FORMS absent | tester | Absence receipt | `python -c "import pathlib,sys; t=pathlib.Path('core/.agent/workflows/create-plan.md').read_text(encoding='utf-8'); bad=('docs/execution/plans/PLAN-TEMPLATE','docs/execution/plans/TASK-TEMPLATE','handoffs/REVIEW-TEMPLATE','rtk proxy','uv run','pwsh -NoProfile -Command'); sys.exit(1 if any(x in t for x in bad) else 0)" *> $env:RECEIPTS_DIR/ac-forbidden.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/ac-forbidden.txt; exit $code` | 3 | shared | C:/Temp/agentic-framework/receipts/ac-forbidden.txt | `coordinator` | `[x]` |
| 3b | AC-1/2: required adopted-tree template paths present | tester | Presence receipt | `python -c "import pathlib,sys; t=pathlib.Path('core/.agent/workflows/create-plan.md').read_text(encoding='utf-8'); need=('.agent/templates/PLAN-TEMPLATE.md','.agent/templates/TASK-TEMPLATE.md','.agent/templates/REVIEW-TEMPLATE.md'); sys.exit(0 if all(x in t for x in need) else 1)" *> $env:RECEIPTS_DIR/ac-present.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/ac-present.txt; exit $code` | 3 | shared | C:/Temp/agentic-framework/receipts/ac-present.txt | `coordinator` | `[x]` |
| 3c | AC-4: every validate_codebase mention is the exists-carve-out | tester | Carve-out receipt | `python -c "import pathlib,sys; hits=[ln for ln in pathlib.Path('core/.agent/workflows/create-plan.md').read_text(encoding='utf-8').splitlines() if 'validate_codebase' in ln]; sys.exit(0 if all(('unless' in h or 'exists' in h or 'do not call' in h) for h in hits) else 1)" *> $env:RECEIPTS_DIR/ac-validate-codebase.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/ac-validate-codebase.txt; exit $code` | 3 | shared | C:/Temp/agentic-framework/receipts/ac-validate-codebase.txt | `coordinator` | `[x]` |
| 3d | AC-3: unguarded origin build-plan cat is gone | tester | D3 receipt | `python -c "import pathlib,sys; t=pathlib.Path('core/.agent/workflows/create-plan.md').read_text(encoding='utf-8'); sys.exit(1 if 'cat docs/build-plan/build-priority-matrix.md' in t else 0)" *> $env:RECEIPTS_DIR/ac-d3.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/ac-d3.txt; exit $code` | 3 | shared | C:/Temp/agentic-framework/receipts/ac-d3.txt | `coordinator` | `[x]` |
| 3e | AC-5: PROJECT-PROFILE.md is a prerequisite | tester | Profile receipt | `python -c "import pathlib,sys; t=pathlib.Path('core/.agent/workflows/create-plan.md').read_text(encoding='utf-8'); sys.exit(0 if 'PROJECT-PROFILE.md' in t else 1)" *> $env:RECEIPTS_DIR/ac-profile.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/ac-profile.txt; exit $code` | 3 | shared | C:/Temp/agentic-framework/receipts/ac-profile.txt | `coordinator` | `[x]` |
| 3f | AC-7: Graphify/Headroom absence is not_applicable without waiting | tester | Context-tool receipt | `python -c "import pathlib,sys; t=pathlib.Path('core/.agent/workflows/create-plan.md').read_text(encoding='utf-8'); sys.exit(0 if 'not_applicable' in t and 'without waiting' in t else 1)" *> $env:RECEIPTS_DIR/ac-graphify.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/ac-graphify.txt; exit $code` | 3 | shared | C:/Temp/agentic-framework/receipts/ac-graphify.txt | `coordinator` | `[x]` |
| 3g | AC-7: GUI 4A skips when named files are absent | tester | GUI-skip receipt | `python -c "import pathlib,sys; t=pathlib.Path('core/.agent/workflows/create-plan.md').read_text(encoding='utf-8'); sys.exit(0 if 'gui-refs-not-shipped' in t else 1)" *> $env:RECEIPTS_DIR/ac-gui.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/ac-gui.txt; exit $code` | 3 | shared | C:/Temp/agentic-framework/receipts/ac-gui.txt | `coordinator` | `[x]` |
| 3h | AC-8: PROFILE-forbidden dispatch is not SIGN 1 | tester | Egress receipt | `python -c "import pathlib,sys; t=pathlib.Path('core/.agent/workflows/create-plan.md').read_text(encoding='utf-8'); sys.exit(0 if 'not SIGN 1' in t else 1)" *> $env:RECEIPTS_DIR/ac-egress.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/ac-egress.txt; exit $code` | 3 | shared | C:/Temp/agentic-framework/receipts/ac-egress.txt | `coordinator` | `[x]` |
| 3i | AC-9: OpenAPI and session-digest are skip-with-basis when unshipped | tester | Skip-basis receipt | `python -c "import pathlib,sys; t=pathlib.Path('core/.agent/workflows/create-plan.md').read_text(encoding='utf-8'); sys.exit(0 if 'skip-with-basis' in t else 1)" *> $env:RECEIPTS_DIR/ac-skip-basis.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/ac-skip-basis.txt; exit $code` | 3 | shared | C:/Temp/agentic-framework/receipts/ac-skip-basis.txt | `coordinator` | `[x]` |
| 4 | BUILD_PLAN hub N/A | orchestrator | Skip receipt | `Test-Path docs/BUILD_PLAN.md *> $env:RECEIPTS_DIR/build-plan-hub.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/build-plan-hub.txt; exit $code` | 3i | shared | C:/Temp/agentic-framework/receipts/build-plan-hub.txt | `coordinator` | `[x]` |
| | **Phase H1 — Pre-Review Closeout** — continuation of implementation; do not stop at this divider. | | | | | | | | |
| H1-1 | Re-read this task.md and confirm implementation rows 3-4 and 3a-3i are checked | coder | Source-read | `view_file: docs/execution/plans/2026-09-19-create-plan-adopter-path-fix/task.md` | 4 | shared | task.md | `coordinator` | `[x]` |
| H1-2 | Re-run AC-1/2/6 forbidden-form assertion | tester | Absence receipt | `python -c "import pathlib,sys; t=pathlib.Path('core/.agent/workflows/create-plan.md').read_text(encoding='utf-8'); bad=('docs/execution/plans/PLAN-TEMPLATE','docs/execution/plans/TASK-TEMPLATE','handoffs/REVIEW-TEMPLATE','rtk proxy','uv run','pwsh -NoProfile -Command'); sys.exit(1 if any(x in t for x in bad) else 0)" *> $env:RECEIPTS_DIR/h1-forbidden.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/h1-forbidden.txt; exit $code` | H1-1 | shared | C:/Temp/agentic-framework/receipts/h1-forbidden.txt | `coordinator` | `[x]` |
| H1-3 | Workspace meu-status skip: origin tree has no `.agent/context/meu-status.yaml` | orchestrator | Skip receipt | `python -c "import pathlib,sys; sys.exit(0 if not pathlib.Path('.agent/context/meu-status.yaml').exists() else 1)" *> $env:RECEIPTS_DIR/meu-skip.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/meu-skip.txt; exit $code` | H1-2 | shared | C:/Temp/agentic-framework/receipts/meu-skip.txt | `coordinator` | `[x]` |
| H1-4 | OpenAPI G8 skip: packages/api is not part of this package | tester | Skip receipt | `python -c "import pathlib,sys; sys.exit(0 if not pathlib.Path('packages/api').exists() else 1)" *> $env:RECEIPTS_DIR/openapi-skip.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/openapi-skip.txt; exit $code` | H1-3 | shared | C:/Temp/agentic-framework/receipts/openapi-skip.txt | `coordinator` | `[x]` |
| H1-5 | Read shipped handoff template | orchestrator | Source-read | `view_file: core/templates/HANDOFF-TEMPLATE.md` | H1-4 | compact_continue | core/templates/HANDOFF-TEMPLATE.md | `coordinator` | `[x]` |
| H1-6 | Write the MEU-1 evidence handoff and validate it | orchestrator | Canonical handoff | `python core/tools/validate_closeout_artifacts.py --handoff .agent/context/handoffs/2026-09-19-create-plan-adopter-path-fix-MEU-1-handoff.md --plan docs/execution/plans/2026-09-19-create-plan-adopter-path-fix/implementation-plan.md *> $env:RECEIPTS_DIR/handoff-check.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/handoff-check.txt; exit $code` | H1-5 | compact_continue | .agent/context/handoffs/2026-09-19-create-plan-adopter-path-fix-MEU-1-handoff.md | `coordinator` | `[x]` |
| H1-6a | Prove every plan AC appears in the handoff AC table | tester | AC coverage receipt | `python core/tools/validate_closeout_artifacts.py --plan docs/execution/plans/2026-09-19-create-plan-adopter-path-fix/implementation-plan.md --handoff .agent/context/handoffs/2026-09-19-create-plan-adopter-path-fix-MEU-1-handoff.md --ac-coverage-only *> $env:RECEIPTS_DIR/handoff-ac-check.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/handoff-ac-check.txt; exit $code` | H1-6 | shared | C:/Temp/agentic-framework/receipts/handoff-ac-check.txt | `coordinator` | `[x]` |
| | **Execution Critical Review** — blocking independent-review region; the implementer never authors the verdict. | | | | | | | | |
| H1-7 | Dispatch independent_reviewer through cli-dispatch SKILL; loop corrections to approval or the six-round hard stop | reviewer dispatch / coder corrections | Rolling implementation review | `python core/tools/validate_closeout_artifacts.py --review .agent/context/handoffs/2026-09-19-create-plan-adopter-path-fix-implementation-critical-review.md --approved-state-only --expected-review-mode execution --expected-target-plan docs/execution/plans/2026-09-19-create-plan-adopter-path-fix/implementation-plan.md --max-review-rounds 6 *> $env:RECEIPTS_DIR/exec-review.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/exec-review.txt; exit $code` | H1-6a | compact_continue | .agent/context/handoffs/2026-09-19-create-plan-adopter-path-fix-implementation-critical-review.md | `coordinator` | `[x]` |
| | **Phase H2 — Post-Review Closeout** — continue immediately after approval; first re-read task.md. | | | | | | | | |
| H2-1 | Read shipped reflection template and schema | orchestrator | Source-read | `view_file: core/templates/REFLECTION-TEMPLATE.md` | H1-7 | shared | core/templates/REFLECTION-TEMPLATE.md | `coordinator` | `[x]` |
| H2-2 | Create reflection with review churn and Instruction Coverage YAML | orchestrator | Reflection file | `python core/tools/validate_closeout_artifacts.py --reflection docs/execution/reflections/2026-09-19-create-plan-adopter-path-fix-reflection.md --reflection-template core/templates/REFLECTION-TEMPLATE.md --reflection-schema core/.agent/schemas/reflection.v1.yaml *> $env:RECEIPTS_DIR/reflection-check.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/reflection-check.txt; exit $code` | H2-1 | compact_continue | docs/execution/reflections/2026-09-19-create-plan-adopter-path-fix-reflection.md | `coordinator` | `[x]` |
| H2-3 | Append a metrics row naming this project slug, creating docs/execution/metrics.md if needed | orchestrator | Metrics row | `python -c "import pathlib,sys; p=pathlib.Path('docs/execution/metrics.md'); t=p.read_text(encoding='utf-8') if p.exists() else ''; sys.exit(0 if 'create-plan-adopter-path-fix' in t else 1)" *> $env:RECEIPTS_DIR/metrics-check.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/metrics-check.txt; exit $code` | H2-2 | shared | docs/execution/metrics.md | `coordinator` | `[x]` |
| H2-4 | Re-run lint_task_contract on this file | tester | Lint receipt | `python core/tools/lint_task_contract.py --task docs/execution/plans/2026-09-19-create-plan-adopter-path-fix/task.md *> $env:RECEIPTS_DIR/lint-task.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/lint-task.txt; exit $code` | H2-3 | shared | C:/Temp/agentic-framework/receipts/lint-task.txt | `coordinator` | `[x]` |
| H2-5 | Prepare conventional commit-message draft; never commit without human approval | orchestrator | Nonempty draft | `Write-Output 'docs: align create-plan.md with the adopted tree' *> $env:RECEIPTS_DIR/commit-draft.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/commit-draft.txt; exit $code` | H2-4 | shared | C:/Temp/agentic-framework/receipts/commit-draft.txt | `coordinator` | `[x]` |

### Status Legend

| Symbol | Meaning |
|--------|---------|
| `[ ]` | Not started |
| `[/]` | In progress |
| `[x]` | Complete |
| `[B]` | Blocked — evidence-gated |

### Evidence-First & Sequencing Rules (v2.1)

- A row is `[x]` only with a receipt or `view_file` source-read. Row 3+ stay `[ ]` until a human says proceed after plan review.
- H1-6 creates the handoff that H1-6a's validator and H1-7's execution review consume. The implementer never authors `approved`.
- Session-digest is skip-with-basis (AC-9; tools unshipped). OpenAPI is skip-with-basis (H1-4).
- Rows 3a–3i must fail on the current unedited `create-plan.md` and pass only after WP-1.
