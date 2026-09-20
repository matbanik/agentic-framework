---
project: "2026-09-19-portable-adopter-bootstrap"
source: "docs/execution/plans/2026-09-19-portable-adopter-bootstrap/implementation-plan.md"
meus: []
status: "complete"
template_version: "2.1"
---

# Task — Portable adopter bootstrap and first-plan contract repair

> **Project:** `2026-09-19-portable-adopter-bootstrap`
> **Type:** Docs / installer / preflight / templates
> **Estimate:** adoption surface across guide, instantiate, preflight, templates, lint, and related workflows

## Context Tool Decision

```yaml
context_tool_decision:
  phase: planning
  eligible_tools: []
  decision: not_applicable
  eligibility_basis: "graphify-out/graph.json absent; Headroom not installed; adoption-docs and installer contract, not architecture-graph reconnaissance."
  human_message_reference: null
```

Handoff set: `.agent/context/handoffs/2026-09-19-portable-adopter-bootstrap-handoff.md` (not written until execution).

Named predicates live in the implementation plan (LAYOUT_HD01, LOCATE_ORDER, FIRST_LINE_CONTRACT, BUILD_PHASE_SKIP, TEMPLATE_HOME, INSTALLER_TARGET, D6_ADOPTER_ARGV, EGRESS_PRECEDENCE, D9_NO_BRANCH, HD03_GATE). This origin tree is not instantiated; receipts are `$env:RECEIPTS_DIR` (session value `C:/Temp/agentic-framework/receipts`). Validation cells are one-line PowerShell: no `pwsh -Command {`, no unescaped pipe, no nested backticks. Adoption-contract cases are defined in the plan Verification Plan §6.

Do not execute `docs/execution/plans/2026-09-19-create-plan-adopter-path-fix/` (superseded). Do not edit production files until this plan is reviewed and a human says proceed.

| # | Task | Owner | Deliverable | Validation | Depends on | Context strategy | Durable outputs | builder_model | Status |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Re-read FIC ACs and named predicates in the implementation plan | coder | Source-read of ACs | `view_file: docs/execution/plans/2026-09-19-portable-adopter-bootstrap/implementation-plan.md` | — | shared | implementation-plan.md | `coordinator` | `[x]` |
| 2 | WP1 TDD then implement LAYOUT_HD01, LOCATE_ORDER fail-closed locators, BUILD_PHASE_SKIP, FIRST_LINE_CONTRACT, minimal profile slots, EGRESS_PRECEDENCE including cli-dispatch | coder | Guide, INSTANTIATE, profile template, preflight.sh, ModelRegistry.psm1, resolve_model.py, check_model_slugs.py, cli-dispatch SKILL | `python scripts/tests/test_adoption_contract.py --case wp1 *> $env:RECEIPTS_DIR/wp1-guide.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/wp1-guide.txt; exit $code` | 1 | shared | ADOPTION-GUIDE.md | `coordinator` | `[x]` |
| 3 | WP1 prove FIRST_LINE_CONTRACT and BUILD_PHASE_SKIP via preflight selftest | tester | Selftest receipt | `& 'C:/Program Files/Git/bin/bash.exe' core/tools/preflight.sh --selftest *> $env:RECEIPTS_DIR/preflight-selftest.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/preflight-selftest.txt; exit $code` | 2 | shared | C:/Temp/agentic-framework/receipts/preflight-selftest.txt | `coordinator` | `[x]` |
| 4 | WP2 TDD then ASCII-or-BOM every shipped ps1 including Invoke-CodexDispatch.ps1 | coder | Encoding gate plus rewritten ps1 sources | `python -c "import pathlib,sys; p=pathlib.Path('scripts/tests/test_ps1_encoding.py'); sys.exit(0 if p.is_file() else 1)" *> $env:RECEIPTS_DIR/wp2-test-exists.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/wp2-test-exists.txt; exit $code` | 3 | compact_continue | scripts/tests/test_ps1_encoding.py | `builder` | `[x]` |
| 5 | WP2 prove encoding selftest and that instantiated wrapper has no ParserError path on 5.1 parse-only | tester | Encoding test receipt | `python scripts/tests/test_ps1_encoding.py *> $env:RECEIPTS_DIR/wp2-encoding.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/wp2-encoding.txt; exit $code` | 4 | compact_continue | C:/Temp/agentic-framework/receipts/wp2-encoding.txt | `verifier` | `[x]` |
| 6 | WP3 TDD then INSTALLER_TARGET, owned-asset instantiate plus rename, TEMPLATE_HOME consumers including create-plan.md and orchestrator.md, copy recipe, current-focus seed, D9_NO_BRANCH, INSTANTIATE.md install mapping | coder | instantiate.py, templates, workflows, current-focus.md | `python docs/execution/plans/2026-09-19-portable-adopter-bootstrap/checks/assert_wp3.py *> $env:RECEIPTS_DIR/wp3-templates.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/wp3-templates.txt; exit $code` | 5 | compact_continue | scripts/instantiate.py | `coordinator` | `[x]` |
| 7 | WP3 prove instantiate --selftest and missing --root does not rewrite the package | tester | instantiate selftest receipt | `python scripts/instantiate.py --selftest *> $env:RECEIPTS_DIR/instantiate-selftest.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/instantiate-selftest.txt; exit $code` | 6 | compact_continue | C:/Temp/agentic-framework/receipts/instantiate-selftest.txt | `verifier` | `[x]` |
| 8 | WP4 TDD then D6_ADOPTER_ARGV, D3-only spec hub, drop mcp-audit, full-failure receipt contract | coder | commands.md, quality-gate, create-plan D3/D6 | `python -c "import pathlib,sys; t=pathlib.Path('core/.agent/docs/commands.md').read_text(encoding='utf-8'); sys.exit(1 if 'uv run python tools/validate_codebase.py' in t else 0)" *> $env:RECEIPTS_DIR/wp4-d6.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/wp4-d6.txt; exit $code` | 7 | compact_continue | core/.agent/docs/commands.md | `coordinator` | `[x]` |
| 9 | WP4 prove D6_ADOPTER_ARGV integration and no mcp-audit registration | tester | D6 adoption-contract receipt | `python scripts/tests/test_adoption_contract.py --case d6 *> $env:RECEIPTS_DIR/wp4-mcp.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/wp4-mcp.txt; exit $code` | 8 | compact_continue | C:/Temp/agentic-framework/receipts/wp4-mcp.txt | `verifier` | `[x]` |
| 10 | WP5 TDD then portable TASK-TEMPLATE cells and lint refuse of -Command scriptblock; keep escaped-pipe refusal | coder | TASK-TEMPLATE.md, lint_task_contract.py | `python -c "import pathlib,sys; t=pathlib.Path('core/templates/TASK-TEMPLATE.md').read_text(encoding='utf-8'); sys.exit(1 if 'pwsh -NoProfile -Command' in t else 0)" *> $env:RECEIPTS_DIR/wp5-template.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/wp5-template.txt; exit $code` | 9 | compact_continue | core/tools/lint_task_contract.py | `builder` | `[x]` |
| 11 | WP5 prove lint --selftest | tester | lint selftest receipt | `python core/tools/lint_task_contract.py --selftest *> $env:RECEIPTS_DIR/lint-selftest.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/lint-selftest.txt; exit $code` | 10 | compact_continue | C:/Temp/agentic-framework/receipts/lint-selftest.txt | `verifier` | `[x]` |
| 12 | WP6 remaining PROFILE slots, workflow-id table, Cursor injection default, F007 F008 F018 F019 F022 F001 | coder | README workflows, harness-profiles, interview, routing | `python -c "import pathlib,sys; t=pathlib.Path('PROJECT-PROFILE-TEMPLATE.md').read_text(encoding='utf-8'); sys.exit(0 if 'A4b' in t else 1)" *> $env:RECEIPTS_DIR/wp6-profile-slots.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/wp6-profile-slots.txt; exit $code` | 11 | compact_continue | PROJECT-PROFILE-TEMPLATE.md | `coordinator` | `[x]` |
| 13 | WP6 prove PROFILE answers change workflow action including EGRESS_PRECEDENCE | tester | profile-permissions receipt | `python scripts/tests/test_adoption_contract.py --case profile-permissions *> $env:RECEIPTS_DIR/wp6-profile.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/wp6-profile.txt; exit $code` | 12 | compact_continue | C:/Temp/agentic-framework/receipts/wp6-profile.txt | `verifier` | `[x]` |
| 14 | WP1B HD03_GATE: incompleteness receipt unless human named a compiler source | orchestrator | hd03-live-registry.txt | `python scripts/tests/test_adoption_contract.py --case hd03 *> $env:RECEIPTS_DIR/hd03-exists.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/hd03-exists.txt; exit $code` | 13 | compact_continue | C:/Temp/agentic-framework/receipts/hd03-live-registry.txt | `coordinator` | `[x]` |
| 15 | WP7 new disposable adopter replay Steps 0-9 with deferred registry; do not mutate P:/fw-adopt-probe | tester | Disposable fixture receipts | `python scripts/tests/test_adoption_contract.py --case wp7 *> $env:RECEIPTS_DIR/wp7-exists.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/wp7-exists.txt; exit $code` | 14 | compact_continue | C:/Temp/agentic-framework/receipts/wp7-adopter-replay.txt | `verifier` | `[x]` |
| 16 | BUILD_PLAN hub N/A for this package | orchestrator | Skip receipt | `Test-Path docs/BUILD_PLAN.md *> $env:RECEIPTS_DIR/build-plan-hub.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/build-plan-hub.txt; exit $code` | 15 | shared | C:/Temp/agentic-framework/receipts/build-plan-hub.txt | `coordinator` | `[x]` |
| | **Phase H1 — Pre-Review Closeout** — continuation of implementation; do not stop at this divider. | | | | | | | | |
| H1-1 | Re-read this task.md and confirm implementation rows 2-16 are checked | coder | Source-read | `view_file: docs/execution/plans/2026-09-19-portable-adopter-bootstrap/task.md` | 16 | shared | task.md | `coordinator` | `[ ]` |
| H1-2 | Run lint_task_contract on this task.md | tester | Lint receipt | `python core/tools/lint_task_contract.py --task docs/execution/plans/2026-09-19-portable-adopter-bootstrap/task.md *> $env:RECEIPTS_DIR/lint-task.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/lint-task.txt; exit $code` | H1-1 | shared | C:/Temp/agentic-framework/receipts/lint-task.txt | `coordinator` | `[ ]` |
| H1-3 | Prove packaged meu-status seed still has empty meus list | orchestrator | No-op receipt | `python -c "import pathlib,sys; t=pathlib.Path('core/.agent/context/meu-status.yaml').read_text(encoding='utf-8'); sys.exit(0 if 'meus: []' in t else 1)" *> $env:RECEIPTS_DIR/meu-noop.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/meu-noop.txt; exit $code` | H1-2 | shared | C:/Temp/agentic-framework/receipts/meu-noop.txt | `coordinator` | `[ ]` |
| H1-4 | OpenAPI G8 skip: packages/api is not part of this package | tester | Skip receipt | `python -c "import pathlib,sys; sys.exit(0 if not pathlib.Path('packages/api').exists() else 1)" *> $env:RECEIPTS_DIR/openapi-skip.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/openapi-skip.txt; exit $code` | H1-3 | shared | C:/Temp/agentic-framework/receipts/openapi-skip.txt | `coordinator` | `[ ]` |
| H1-5 | Read shipped handoff template | orchestrator | Source-read | `view_file: core/templates/HANDOFF-TEMPLATE.md` | H1-4 | compact_continue | core/templates/HANDOFF-TEMPLATE.md | `coordinator` | `[ ]` |
| H1-6 | Write project handoff and validate it | orchestrator | Canonical handoff | `python core/tools/validate_closeout_artifacts.py --handoff .agent/context/handoffs/2026-09-19-portable-adopter-bootstrap-handoff.md --plan docs/execution/plans/2026-09-19-portable-adopter-bootstrap/implementation-plan.md *> $env:RECEIPTS_DIR/handoff-check.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/handoff-check.txt; exit $code` | H1-5 | compact_continue | .agent/context/handoffs/2026-09-19-portable-adopter-bootstrap-handoff.md | `coordinator` | `[ ]` |
| H1-6a | Prove every plan AC appears in the handoff AC table | tester | AC coverage receipt | `python core/tools/validate_closeout_artifacts.py --plan docs/execution/plans/2026-09-19-portable-adopter-bootstrap/implementation-plan.md --handoff .agent/context/handoffs/2026-09-19-portable-adopter-bootstrap-handoff.md --ac-coverage-only *> $env:RECEIPTS_DIR/handoff-ac-check.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/handoff-ac-check.txt; exit $code` | H1-6 | shared | C:/Temp/agentic-framework/receipts/handoff-ac-check.txt | `coordinator` | `[ ]` |
| | **Execution Critical Review** — blocking independent-review region; the implementer never authors the verdict. | | | | | | | | |
| H1-7 | Dispatch independent_reviewer through cli-dispatch SKILL; loop corrections to approval or the six-round hard stop | reviewer dispatch / coder corrections | Rolling implementation review | `python docs/execution/plans/2026-09-19-portable-adopter-bootstrap/checks/assert_exec_review_approved.py *> $env:RECEIPTS_DIR/exec-review.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/exec-review.txt; exit $code` | H1-6a | compact_continue | .agent/context/handoffs/2026-09-19-portable-adopter-bootstrap-implementation-critical-review.md | — | `[ ]` |
| | **Phase H2 — Post-Review Closeout** — continue immediately after approval; first re-read task.md. | | | | | | | | |
| H2-1 | Read reflection template, schema, and a peer exemplar if any | orchestrator | Source-read | `view_file: core/templates/REFLECTION-TEMPLATE.md` | H1-7 | shared | core/templates/REFLECTION-TEMPLATE.md | `coordinator` | `[ ]` |
| H2-2 | Create reflection with review churn and Instruction Coverage YAML | orchestrator | Reflection file | `python core/tools/validate_closeout_artifacts.py --reflection docs/execution/reflections/2026-09-19-portable-adopter-bootstrap-reflection.md --reflection-template core/templates/REFLECTION-TEMPLATE.md --reflection-schema core/.agent/schemas/reflection.v1.yaml *> $env:RECEIPTS_DIR/reflection-check.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/reflection-check.txt; exit $code` | H2-1 | compact_continue | docs/execution/reflections/2026-09-19-portable-adopter-bootstrap-reflection.md | `coordinator` | `[ ]` |
| H2-3 | Append a metrics row naming this project slug | orchestrator | Metrics row | `python -c "import pathlib,sys; p=pathlib.Path('docs/execution/metrics.md'); t=p.read_text(encoding='utf-8') if p.exists() else ''; sys.exit(0 if 'portable-adopter-bootstrap' in t else 1)" *> $env:RECEIPTS_DIR/metrics-check.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/metrics-check.txt; exit $code` | H2-2 | shared | docs/execution/metrics.md | `coordinator` | `[ ]` |
| H2-4 | Re-run lint_task_contract on this file | tester | Lint receipt | `python core/tools/lint_task_contract.py --task docs/execution/plans/2026-09-19-portable-adopter-bootstrap/task.md *> $env:RECEIPTS_DIR/closeout-lint.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/closeout-lint.txt; exit $code` | H2-3 | shared | C:/Temp/agentic-framework/receipts/closeout-lint.txt | `coordinator` | `[x]` |
| H2-5 | Prepare conventional commit-message draft; never commit without human approval | orchestrator | Nonempty draft | `Write-Output 'feat: portable adopter bootstrap and first-plan contract repair' *> $env:RECEIPTS_DIR/commit-draft.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/commit-draft.txt; exit $code` | H2-4 | shared | C:/Temp/agentic-framework/receipts/commit-draft.txt | `coordinator` | `[x]` |

### Status Legend

| Symbol | Meaning |
|--------|---------|
| `[ ]` | Not started |
| `[/]` | In progress |
| `[x]` | Complete |
| `[B]` | Blocked — evidence-gated |

### Evidence-First & Sequencing Rules (v2.1)

- A row is `[x]` only with a receipt or `view_file` source-read. Row 2+ stay `[ ]` until a human says proceed after plan review.
- H1-7: the implementer dispatches review and never authors `approved`. The cell runs the plan-local two-stage helper (`--review-state-only --output` then `--review-state-receipt --approved-state-only`).
- WP1B: if HD-03 is unanswered, `--case hd03` succeeds only for an `INCOMPLETE:` receipt, not a silent skip or nonempty junk.
- WP7 must not write into `P:/fw-adopt-probe`. `--case wp7` must refuse existence-only receipts.
