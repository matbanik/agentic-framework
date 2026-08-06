---
project: "{YYYY-MM-DD}-{project-slug}"
source: "docs/execution/plans/{YYYY-MM-DD}-{project-slug}/implementation-plan.md"
meus: ["{MEU-ID-1}", "{MEU-ID-2}"]
status: "in_progress"
template_version: "2.1"
---

# Task — {Project Title}

> **Project:** `{YYYY-MM-DD}-{project-slug}`
> **Type:** {Infrastructure/Docs | Domain | API | GUI | MCP}
> **Estimate:** {N files changed}

## Context Tool Decision

```yaml
context_tool_decision:
  phase: planning | execution | planning_and_execution
  eligible_tools: [graphify, graphify-research, headroom]
  decision: use | accepted_loss | not_applicable
  eligibility_basis: "{specific graph/payload/scope evidence}"
  human_message_reference: "{USER_EXPLICIT date/summary; null only for not_applicable}"
```

## Task Table

> Classify every validation command through
> [`.agent/docs/output-evidence-policy.md`](../../../.agent/docs/output-evidence-policy.md).
> Use verified native RTK for compact views and `rtk proxy` for exact evidence.
>
> **Handoff set:** product projects name one
> `.agent/context/handoffs/{date}-{project-slug}-{MEU-ID}-handoff.md` per MEU in the
> deliverable rows. Non-product `meus: []` projects name one project handoff at
> `.agent/context/handoffs/{date}-{project-slug}-handoff.md`. The rolling project
> review filename remains `{project-folder}-implementation-critical-review.md`.
>
> Column schema: **Depends on** = `depends_on`, **Context strategy** =
> `context_strategy`, **Durable outputs** = `durable_outputs`, and optional
> **`builder_model`** (10-column tables). Legacy 9-column tables remain valid.
> Cursor builder pins: `{composer-2.5-fast|cursor-grok-4.5-high-fast}`; Claude:
> `{opus-5|sonnet-5}`; never `auto` / Fable 5 as builder.

| # | Task | Owner | Deliverable | Validation | Depends on | Context strategy | Durable outputs | builder_model | Status |
|---|---|---|---|---|---|---|---|---|---|
| 1 | {first implementation task} | coder | {deliverable} | `{exact command}` | — | shared | {repo/receipt path} | `{composer-2.5-fast\|cursor-grok-4.5-high-fast}` | `[ ]` |
| 2 | {second implementation task} | coder | {deliverable} | `{exact command}` | 1 | compact_continue | {durable path; compact then re-read task + this output} | `cursor-grok-4.5-high-fast` | `[ ]` |
| ... | ... | ... | ... | ... | ... | ... | ... | ... | ... |

`context_strategy` must be `shared|compact_continue|isolated`. Dependencies must name
existing rows and form an acyclic graph. Every non-`shared` row must name a durable
output and lifecycle action. `isolated` is valid only with an authorized fresh-worker
capability; otherwise change it to `compact_continue` before execution.

> **Optional `delegate_to` annotation.** A row may name an in-harness subagent for delegation by
> adding `delegate_to: {{PROJECT_NAME}}-builder` (or `{{PROJECT_NAME}}-verifier`) **inside the row's Task cell** —
> it is prose metadata, NOT a new column and NOT a value of `context_strategy` (whose enum stays
> exactly `shared|compact_continue|isolated`). The delegation decision itself is governed by
> [`.agent/skills/subagent-delegation/SKILL.md`](../../../.agent/skills/subagent-delegation/SKILL.md);
> the annotation only records the intended worker when `fresh_worker` resolves.

> **Closeout is one continuous execution pass, split by the review barrier (v2.1).**
> Phase **H1** (pre-review) finishes the implementation, all artifact updates, and the
> **handoff** (the review's target). The **Execution Critical Review** is then dispatched
> and looped to `approved`. Phase **H2** (post-review) writes the reflection/metrics/session
> save — these RECORD the review outcome and therefore *cannot* be written before the review.
> "Continuous pass" means: complete H1 → dispatch → loop corrections → complete H2 **without
> stopping** (the only valid pauses are the five turn-enders in `AGENTS.md` §Execution Contract:
> DONE, round cap, both reviewers rate-limited, ~50% context checkpoint, human-decision gate). Do
> NOT report completion or ask the user to approve between phases.
>
> **The phase-divider rows below are NOT stop points.** They mark *ordering* (H2 must record the
> review, so it follows H1), not *turn boundaries*. The boundary between any two phases is the most
> common place the agent offers a "politeness off-ramp" — these are VIOLATIONS, not courtesies:
> - ❌ "Want me to continue with the H1/H2 closeout, or handle it in a separate session?"
> - ❌ "Implementation/review complete — shall I proceed to the reflection?"
> - ❌ "This looks like a good stopping point. Let me know if you'd like me to continue."

| | **📋 Phase H1 — Pre-Review Closeout** — continuation of implementation; do not stop at this divider. | | | | | | | | |
| H1-1 | Re-read this `task.md` and prove no implementation row remains unchecked. | coder | Exact unchecked-row receipt | `rtk proxy pwsh -NoProfile -Command { ... } *> {{RECEIPTS_DIR}}/task-unchecked.txt; $code=$LASTEXITCODE; Get-Content {{RECEIPTS_DIR}}/task-unchecked.txt; exit $code` | `{last-task-id}` | shared | `task.md`; exact receipt | `cursor-grok-4.5-high-fast` | `[ ]` |
| H1-2 | Run the registered verification plan. | tester | All blocking checks pass | `{exact command(s) from implementation-plan.md}` | H1-1 | shared | Gate receipts | `cursor-grok-4.5-high-fast` | `[ ]` |
| H1-3 | For product MEUs, update/render/check MEU status and current focus. For `meus: []`, prove the registered product-state no-op. | orchestrator | SSOT rendered or no-op receipt | `rtk proxy uv run python tools/meu_status.py render --check *> {{RECEIPTS_DIR}}/drift-check.txt; $code=$LASTEXITCODE; Get-Content {{RECEIPTS_DIR}}/drift-check.txt; exit $code` | H1-2 | shared | SSOT/no-op receipt | `cursor-grok-4.5-high-fast` | `[ ]` |
| H1-4 | If `packages/api/` changed, check OpenAPI drift and regenerate only on detected drift; otherwise record the skip basis. | tester | OpenAPI receipt or scoped skip | `rtk proxy uv run python tools/export_openapi.py --check openapi.committed.json *> {{RECEIPTS_DIR}}/openapi-check.txt; $code=$LASTEXITCODE; Get-Content {{RECEIPTS_DIR}}/openapi-check.txt; exit $code` | H1-3 | shared | OpenAPI receipt | `cursor-grok-4.5-high-fast` | `[ ]` |
| H1-5 | Read the handoff template and deterministic latest peer exemplar. | orchestrator | Source-read receipt | `view_file: .agent/context/handoffs/TEMPLATE.md` plus latest peer handoff | H1-4 | compact_continue | Template/exemplar receipt; compact_continue fallback | `cursor-grok-4.5-high-fast` | `[ ]` |
| H1-6 | Create the complete evidence handoff. Product: `.agent/context/handoffs/{date}-{project-slug}-{MEU-ID}-handoff.md` per MEU. Non-product `meus: []`: `.agent/context/handoffs/{date}-{project-slug}-handoff.md`. | orchestrator | Canonical handoff set | `rtk proxy uv run python tools/validate_closeout_artifacts.py --handoff {handoff-file} --plan {plan-file} *> {{RECEIPTS_DIR}}/handoff-check.txt; $code=$LASTEXITCODE; Get-Content {{RECEIPTS_DIR}}/handoff-check.txt; exit $code` | H1-5 | compact_continue | Canonical handoff(s); compact_continue fallback | `cursor-grok-4.5-high-fast` | `[ ]` |
| H1-6a | Prove every plan AC appears in the handoff AC table. | tester | Complete target-bound AC set | `rtk proxy uv run python tools/validate_closeout_artifacts.py --plan {plan-file} --handoff {handoff-file} *> {{RECEIPTS_DIR}}/handoff-ac-check.txt; $code=$LASTEXITCODE; Get-Content {{RECEIPTS_DIR}}/handoff-ac-check.txt; exit $code` | H1-6 | shared | AC validation receipt | `cursor-grok-4.5-high-fast` | `[ ]` |
| | **🔎 Execution Critical Review** — blocking independent-review region; the implementer never authors the verdict. | | | | | | | | |
| H1-7 | Dispatch GPT-5.6 Sol through `cli-dispatch/SKILL.md`; loop corrections to approval or the six-round hard stop. | reviewer dispatch / coder corrections | Rolling implementation review plus target-bound approval receipt | `rtk proxy pwsh -NoProfile -Command { rtk proxy uv run python tools/validate_closeout_artifacts.py --review .agent/context/handoffs/{date}-{project-slug}-implementation-critical-review.md --review-state-only --expected-review-mode execution --expected-target-plan docs/execution/plans/{date}-{project-slug}/implementation-plan.md --max-review-rounds 6 --output {{RECEIPTS_DIR}}/exec-review-state.json; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; rtk proxy uv run python tools/validate_closeout_artifacts.py --review .agent/context/handoffs/{date}-{project-slug}-implementation-critical-review.md --review-state-receipt {{RECEIPTS_DIR}}/exec-review-state.json --approved-state-only --expected-review-mode execution --expected-target-plan docs/execution/plans/{date}-{project-slug}/implementation-plan.md --max-review-rounds 6; exit $LASTEXITCODE } *> {{RECEIPTS_DIR}}/exec-review.txt; $code=$LASTEXITCODE; Get-Content {{RECEIPTS_DIR}}/exec-review.txt; exit $code` | H1-6a | isolated | Rolling review; approval receipt; compact_continue fallback | — | `[ ]` |
| | **📋 Phase H2 — Post-Review Closeout** — continue immediately after approval; first re-read `task.md`. | | | | | | | | |
| H2-1 | Read the reflection template, schema, and deterministic latest peer exemplar. | orchestrator | Source-read receipt | `view_file: docs/execution/reflections/TEMPLATE.md`, `.agent/schemas/reflection.v1.yaml`, and latest peer reflection | H1-7 | shared | Reflection source receipt | `cursor-grok-4.5-high-fast` | `[ ]` |
| H2-2 | Create the full reflection with review churn and Instruction Coverage YAML. | orchestrator | `docs/execution/reflections/{date}-{project-slug}-reflection.md` | `rtk proxy uv run python tools/validate_closeout_artifacts.py --reflection {reflection-file} --reflection-template docs/execution/reflections/TEMPLATE.md --reflection-schema .agent/schemas/reflection.v1.yaml *> {{RECEIPTS_DIR}}/reflection-check.txt; $code=$LASTEXITCODE; Get-Content {{RECEIPTS_DIR}}/reflection-check.txt; exit $code` | H2-1 | compact_continue | Reflection; compact_continue fallback | `cursor-grok-4.5-high-fast` | `[ ]` |
| H2-3 | Append and verify the metrics row. | orchestrator | Populated metrics row | `rtk proxy pwsh -NoProfile -Command { Get-Content docs/execution/metrics.md -Tail 3 } *> {{RECEIPTS_DIR}}/metrics-check.txt; $code=$LASTEXITCODE; Get-Content {{RECEIPTS_DIR}}/metrics-check.txt; exit $code` | H2-2 | shared | Metrics receipt | `cursor-grok-4.5-high-fast` | `[ ]` |
| H2-4 | Run complete closeout structural, handoff, approval, and metrics checks. | tester | Passing completion-preflight receipt | `{target-bound validate_closeout_artifacts.py command}` | H2-3 | shared | Closeout receipt | `cursor-grok-4.5-high-fast` | `[ ]` |
| H2-5 | Prepare conventional commit-message suggestions; never commit without human approval. | orchestrator | Fresh nonempty draft | `rtk proxy pwsh -NoProfile -Command { ...write and verify draft... } *> {{RECEIPTS_DIR}}/commit-draft.txt; $code=$LASTEXITCODE; Get-Content {{RECEIPTS_DIR}}/commit-draft.txt; exit $code` | H2-4 | shared | Commit-message draft | `cursor-grok-4.5-high-fast` | `[ ]` |

### Status Legend

| Symbol | Meaning |
|--------|---------|
| `[ ]` | Not started |
| `[/]` | In progress |
| `[x]` | Complete |
| `[B]` | Blocked — evidence-gated (closed reason list + pasted error; must link follow-up) |

### Evidence-First & Sequencing Rules (v2.1)

- **Evidence-first completion:** a row is `[x]` only when its deliverable exists and the handoff/walkthrough carries the evidence bundle (AGENTS.md §Execution Contract).
- **The review barrier resolves the old reflection↔review cycle:** the handoff (H1-6) is created *before* the review (it is the review's input); the reflection/metrics (H2) are created *after* `approved` so they can record the verdict. Do not create H2 artifacts during H1, and do not dispatch the review (H1-7) before the handoff exists.
- **Self-review prohibition:** the implementing agent dispatches and collects the H1-7 review; it never authors the `approved` verdict itself (AGENTS.md §Execution Contract).
- **`[B]` is evidence-gated:** valid ONLY for (a) a reproduced *external* error, (b) a missing dependency/credential/permission, or (c) a human-decision gate — each with a linked follow-up and, for (a)/(b), the pasted command + error (a `{{RECEIPTS_DIR}}/` redirect path a reviewer can re-open). Subjective reasons ("too complex", "no time", "out of scope", "later") are invalid; no error artifact ⇒ not blocked ⇒ keep working (AGENTS.md §Execution Contract).
- **Dispatching the H1-7 review is a blocking step, not a turn boundary:** continue to H2 in the same pass once the `approved` verdict file lands. The only sanctioned turn-enders are DONE, the round cap, both reviewers rate-limited, the ~50% context checkpoint, or a human-decision gate (AGENTS.md §Execution Contract).
