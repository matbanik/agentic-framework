---
project: "{YYYY-MM-DD}-{project-slug}"
source: "docs/execution/plans/{YYYY-MM-DD}-{project-slug}/implementation-plan.md"
meus: ["{MEU-ID-1}", "{MEU-ID-2}"]
status: "in_progress"
template_version: "2.5"
stop_gate: "armed"  # optional: "armed" | "released:<round-cap|reviewer-unavailable|human-gate|handback|done>" (tools/stop_gate.py)
run_parameters:  # optional (v2.4): the block create-plan.md Step 0 resolves; absent = the earlier rules
  schema: run-parameters/1
  decisions: "{hdp | human-all}"
  commit_plan: "{true | false}"
  exec_after_plan: "{true | false}"
  commit_exec: "{true | false}"
  push: never
  tightened_from: "{none | grouping | plan}"
  authorization: "{the authorization/1 block from Step 0 | {schema: manual}}"
bound_sessions: []  # written by tools/run_parameters.py bind --plan, never by hand
review_limits:  # optional (v2.5): equal to the plan's block; absent = .agent/review-limits.json
  schema: review-limits/1
  plan_rounds: "{integer >= 1}"
  execution_rounds: "{integer >= 1}"
  plan_tokens: "{integer >= 1 | off}"
  execution_tokens: "{integer >= 1 | off}"
  basis: "{repo | tightened | loosened}"
---

# Task — {Project Title}

> **Project:** `{YYYY-MM-DD}-{project-slug}`
> **Type:** {Infrastructure/Docs | Domain | API | GUI | MCP}
> **Estimate:** {N files changed}
>
> **v2.4 — run parameters.** The optional `run_parameters` block (`create-plan.md` Step 0) adds
> the `PC` row (commit the approved plan, `create-plan.md` §5d), the `COMMIT` row and the H2-6
> finalize row. The H2-5a seal row is gone: the final audit and the seal are terminal steps, not
> rows. `[x] n/a` is valid for `PC` under `commit_plan: false` and for `COMMIT` under
> `commit_exec: false`. A task without the block keeps the earlier rules.
>
> **v2.5 — review limits.** The optional `review_limits` block (`create-plan.md` Step 0) equals
> the plan's and sets the plan and execution review loops' round and token limits; a task
> without it takes `.agent/review-limits.json` (the ledger's constants when the file is
> absent), as before. `{configured-cap}` in H1-7a and H1-7b is the execution loop's round cap
> as the ledger holds it: copy it from `python tools/review_ledger.py state --loop-id
> exec-{YYYY-MM-DD}-{project-slug}` (its base budget plus every `continue` grant). The final
> audit reads the same value.

## Context Tool Decision

```yaml
context_tool_decision:
  phase: planning | execution | planning_and_execution
  eligible_tools: [graphify, graphify-research, headroom]
  decision: use | accepted_loss | not_applicable
  eligibility_basis: "{specific graph/payload/scope evidence}"
  human_message_reference: "{USER_EXPLICIT date/summary; null only for not_applicable}"
```

## Lane Ownership

This section is optional. Keep it only when the plan runs as a lane next to other sessions. Only a task with this section can be claimed as a lane: `tools/lanes.py claim` refuses `no_ownership` without it. A task without it runs as before.

Each entry is a repository-relative exact path, or a directory prefix with a trailing `/`. Do not use globs, absolute paths, drive letters, backslashes, `.` or `..`. An `owns` entry and a `must_not_touch` entry must not overlap. A junction file (the `junction_files` list in `.agent/credits/worktree.json`) never goes in `owns`: the integrator edits it, and the lane files an integration request in its handoff.

```yaml
owns:
  - src/example/
  - tests/test_example.py
must_not_touch:
  - .agent/context/
```

## Task Table

> Classify every validation command through PROFILE D6 (D6_ADOPTER_ARGV) and
> [`.agent/docs/output-evidence-policy.md`](../docs/output-evidence-policy.md).
> D6 defines static/targeted/fresh full stages and complete input identity.
> Do not require `rtk` or `uv`. Redirect every process stream to `{{RECEIPTS_DIR}}`.
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
> `builder_model` names a **capability class** — `builder` for mechanical rows,
> `coordinator` for rows needing the dependency graph, `verifier` for read-only
> validation. Never a model slug and never `auto`; resolve the class instead
> (`Resolve-AgentModel -Class builder -Harness <harness> -Project <project-root>`), because which snapshot
> serves a class is the live registry's business (see `.agent/INSTANTIATE.md`)
> and changes without touching this plan.
> `architect` is reserved for its own shape and is never a builder.

| # | Task | Owner | Deliverable | Validation | Depends on | Context strategy | Durable outputs | builder_model | Status |
|---|---|---|---|---|---|---|---|---|---|
| PC | Commit the approved plan (`create-plan.md` §5d): the plan folder, the plan-critical-review handoff and the grouping tracker row, from the `PC` manifest, as one `docs(plan): …` commit through `tools/commit_batch.py` under the verified `plan_commit` grant. Runs once, after the final plan-review `approved`; a failed `PC` blocks row 1. `[x] n/a` under `commit_plan: false`. | orchestrator | Plan commit (or the n/a basis in this row) | `{commit_batch.py command for the PC manifest}` | — | shared | Commit SHA in this row | `coordinator` | `[ ]` |
| 1 | {first implementation task} | coder | {deliverable} | `{exact command}` | PC | shared | {durable repository artifact} | `builder` | `[ ]` |
| 2 | {second implementation task} | coder | {deliverable} | `{exact command}` | 1 | compact_continue | {durable path; compact then re-read task + this output} | `coordinator` | `[ ]` |
| ... | ... | ... | ... | ... | ... | ... | ... | ... | ... |

`context_strategy` must be `shared|compact_continue|isolated`. Dependencies must name
existing rows and form an acyclic graph. Every non-`shared` row must name a durable
output and lifecycle action. `isolated` is valid only with an authorized fresh-worker
capability; otherwise change it to `compact_continue` before execution.

> **Optional `delegate_to` annotation.** A row may name an in-harness subagent for delegation by
> adding `delegate_to: {{PROJECT_NAME}}-builder` (or `{{PROJECT_NAME}}-verifier`) **inside the row's Task cell** —
> it is prose metadata, NOT a new column and NOT a value of `context_strategy` (whose enum stays
> exactly `shared|compact_continue|isolated`). The delegation decision itself is governed by
> [`.agent/skills/subagent-delegation/SKILL.md`](../skills/subagent-delegation/SKILL.md);
> the annotation only records the intended worker when `fresh_worker` resolves.

> **Closeout is one continuous execution pass, split by the review barrier (v2.1).**
> Phase **H1** (pre-review) finishes the implementation, all artifact updates, and the
> **handoff** (the review's target). The **Execution Critical Review** is then dispatched
> and looped to `approved`. Phase **H2** (post-review) writes the reflection/metrics/session
> save — these RECORD the review outcome and therefore *cannot* be written before the review.
> "Continuous pass" means: complete H1 → dispatch → loop corrections → complete H2 **without
> stopping** (the only valid pauses are the four outcomes in `AGENTS.md` §Execution Contract:
> DONE, review cap, reviewer unavailable, human decision; compaction continues). Do
> NOT report completion or ask the user to approve between phases.
>
> **The phase-divider rows below are NOT stop points.** They mark *ordering* (H2 must record the
> review, so it follows H1), not *turn boundaries*. The boundary between any two phases is the most
> common place the agent offers a "politeness off-ramp" — these are VIOLATIONS, not courtesies:
> - ❌ "Want me to continue with the H1/H2 closeout, or handle it in a separate session?"
> - ❌ "Implementation/review complete — shall I proceed to the reflection?"
> - ❌ "This looks like a good stopping point. Let me know if you'd like me to continue."

| | **📋 Phase H1 — Pre-Review Closeout** — continuation of implementation; do not stop at this divider. | | | | | | | | |
| H1-1 | Re-read this `task.md` and prove no implementation row remains unchecked. | coder | Exact unchecked-row receipt | `python -c "import pathlib,sys; t=pathlib.Path('docs/execution/plans/{date}-{project-slug}/task.md').read_text(encoding='utf-8'); bad=[ln for ln in t.splitlines() if ln.startswith(chr(124)) and ln.strip()[1:].split(chr(124),1)[0].strip().strip(chr(96)).isdigit() and '[ ]' in ln]; sys.exit(1 if bad else 0)" *> {{RECEIPTS_DIR}}/task-unchecked.txt; $code=$LASTEXITCODE; Get-Content {{RECEIPTS_DIR}}/task-unchecked.txt; exit $code` | `{last-task-id}` | shared | `task.md`; exact receipt | `coordinator` | `[ ]` |
| H1-2 | Run the registered verification plan. | tester | All blocking checks pass | `{exact command(s) from implementation-plan.md}` | H1-1 | shared | Durable gate observations in handoff | `coordinator` | `[ ]` |
| H1-3 | For product MEUs, update/render/check MEU status and current focus. For `meus: []`, prove the registered product-state no-op. | orchestrator | SSOT rendered or no-op receipt | `python tools/meu_status.py render --check *> {{RECEIPTS_DIR}}/drift-check.txt; $code=$LASTEXITCODE; Get-Content {{RECEIPTS_DIR}}/drift-check.txt; exit $code` | H1-2 | shared | SSOT/no-op receipt | `coordinator` | `[ ]` |
| H1-4 | If `packages/api/` changed, check OpenAPI drift and regenerate only on detected drift; otherwise record the skip basis. | tester | OpenAPI receipt or scoped skip | `python -c "import pathlib,sys; sys.exit(0 if not pathlib.Path('packages/api').exists() else 1)" *> {{RECEIPTS_DIR}}/openapi-check.txt; $code=$LASTEXITCODE; Get-Content {{RECEIPTS_DIR}}/openapi-check.txt; exit $code` | H1-3 | shared | OpenAPI receipt | `coordinator` | `[ ]` |
| H1-5 | Read the handoff template and deterministic latest peer exemplar. | orchestrator | Source-read receipt | `view_file: .agent/templates/HANDOFF-TEMPLATE.md` plus latest peer handoff | H1-4 | compact_continue | Template/exemplar receipt; compact_continue fallback | `coordinator` | `[ ]` |
| H1-6 | Create the complete evidence handoff. Product: `.agent/context/handoffs/{date}-{project-slug}-{MEU-ID}-handoff.md` per MEU. Non-product `meus: []`: `.agent/context/handoffs/{date}-{project-slug}-handoff.md`. | orchestrator | Canonical handoff set | `python tools/validate_closeout_artifacts.py --handoff {handoff-file} --plan {plan-file} *> {{RECEIPTS_DIR}}/handoff-check.txt; $code=$LASTEXITCODE; Get-Content {{RECEIPTS_DIR}}/handoff-check.txt; exit $code` | H1-5 | compact_continue | Canonical handoff(s); compact_continue fallback | `coordinator` | `[ ]` |
| H1-6a | Prove every plan AC appears in the handoff AC table. | tester | Complete target-bound AC set | `python tools/validate_closeout_artifacts.py --plan {plan-file} --handoff {handoff-file} --ac-coverage-only *> {{RECEIPTS_DIR}}/handoff-ac-check.txt; $code=$LASTEXITCODE; Get-Content {{RECEIPTS_DIR}}/handoff-ac-check.txt; exit $code` | H1-6 | shared | AC validation receipt | `coordinator` | `[ ]` |
| H1-6b | Verify fresh full evidence against independently obtained current D6 identity; rerun D6 full if inputs changed or evidence is missing. | tester | Fresh full evidence | `python tools/durable_evidence.py {handoff-file} --require-full --expected-state {actual-state} *> {{RECEIPTS_DIR}}/full-evidence-check.txt; $code=$LASTEXITCODE; Get-Content {{RECEIPTS_DIR}}/full-evidence-check.txt; exit $code` | H1-6a | shared | Handoff evidence.v1 full record | `coordinator` | `[ ]` |
| | **🔎 Execution Critical Review** — blocking independent-review region; the implementer never authors the verdict. | | | | | | | | |
| H1-7 | Dispatch independent reviewer under EGRESS_PRECEDENCE; loop corrections within ledger limits. | reviewer dispatch / coder corrections | Rolling review | `{exact authorized dispatch command with preserved exit}` | H1-6b | isolated | Rolling review; durable findings; compact_continue fallback | — | `[ ]` |
| H1-7a | Parse current review to target-bound state. | tester | Review state receipt | `python tools/validate_closeout_artifacts.py --review {review-file} --review-state-only --expected-review-mode execution --expected-target-plan {plan-file} --max-review-rounds {configured-cap} --output {{RECEIPTS_DIR}}/review-state.json *> {{RECEIPTS_DIR}}/review-state-check.txt; $code=$LASTEXITCODE; Get-Content {{RECEIPTS_DIR}}/review-state-check.txt; exit $code` | H1-7 | shared | Durable review + parsed state | `coordinator` | `[ ]` |
| H1-7b | Require approved current review state and matching ledger verdict. | tester | Verified approval | `python tools/validate_closeout_artifacts.py --review {review-file} --approved-state-only --review-state-receipt {{RECEIPTS_DIR}}/review-state.json --expected-review-mode execution --expected-target-plan {plan-file} --max-review-rounds {configured-cap} *> {{RECEIPTS_DIR}}/exec-review.txt; $code=$LASTEXITCODE; Get-Content {{RECEIPTS_DIR}}/exec-review.txt; exit $code` | H1-7a | shared | Durable approval observation | `coordinator` | `[ ]` |
| | **📋 Phase H2 — Post-Review Closeout** — continue immediately after approval; first re-read `task.md`. | | | | | | | | |
| H2-1 | Read the reflection template, schema, and deterministic latest peer exemplar. | orchestrator | Source-read receipt | `view_file: .agent/templates/REFLECTION-TEMPLATE.md`, `.agent/schemas/reflection.v1.yaml`, and latest peer reflection | H1-7b | shared | Reflection source receipt | `coordinator` | `[ ]` |
| H2-2 | Create the full reflection with review churn and Instruction Coverage YAML. | orchestrator | `docs/execution/reflections/{date}-{project-slug}-reflection.md` | `python tools/validate_closeout_artifacts.py --reflection {reflection-file} --reflection-template .agent/templates/REFLECTION-TEMPLATE.md --reflection-schema .agent/schemas/reflection.v1.yaml --decision-source {plan-file} --decision-source {handoff-file} --decision-source {grouping-file} --decision-source .agent/context/known-issues.yaml --decision-issue {issue-id} *> {{RECEIPTS_DIR}}/reflection-check.txt; $code=$LASTEXITCODE; Get-Content {{RECEIPTS_DIR}}/reflection-check.txt; exit $code` | H2-1 | compact_continue | Reflection; compact_continue fallback | `coordinator` | `[ ]` |
| H2-3 | Append and verify the metrics row. | orchestrator | Populated metrics row | `python -c "import pathlib,sys; p=pathlib.Path('docs/execution/metrics.md'); sys.exit(0 if p.exists() and p.read_text(encoding='utf-8').strip() else 1)" *> {{RECEIPTS_DIR}}/metrics-check.txt; $code=$LASTEXITCODE; Get-Content {{RECEIPTS_DIR}}/metrics-check.txt; exit $code` | H2-2 | shared | Metrics receipt | `coordinator` | `[ ]` |
| H2-3a | If `grouping_source` is set: in that grouping file, mark this session's row terminal (`done` or `blocked — {reason}`) and name the next session (`session-grouping.md` §Output). If `grouping_source: null`, record the no-op basis. | orchestrator | Updated grouping file (or the no-op basis in this `task.md` row) | `python -c "import pathlib,sys; t=pathlib.Path('{grouping-source}').read_text(encoding='utf-8'); sys.exit(0 if '{session-id}' in t else 1)" *> {{RECEIPTS_DIR}}/grouping-tracker-check.txt; $code=$LASTEXITCODE; Get-Content {{RECEIPTS_DIR}}/grouping-tracker-check.txt; exit $code` | H2-3 | shared | Grouping file, or this `task.md` row for the no-op | `coordinator` | `[ ]` |
| H2-3b | If any session MEU resolves a tracked issue (check `meu_links` in `known-issues.yaml`): set `status: resolved` + `resolution` + date via `tools/issue_triage.py`, then regenerate the markdown. Never hand-edit `known-issues.md`. If nothing resolved, record the no-op basis. | orchestrator | Updated `known-issues.yaml` + regenerated `known-issues.md` (or the no-op basis in this `task.md` row) | `python tools/issue_triage.py render *> {{RECEIPTS_DIR}}/known-issues-render.txt; $code=$LASTEXITCODE; Get-Content {{RECEIPTS_DIR}}/known-issues-render.txt; exit $code` | H2-3a | shared | `known-issues.yaml` + `known-issues.md` | `coordinator` | `[ ]` |
| H2-3c | Worktree landing and the product capture. When this project was created with `executor_worktree.py create`, run `executor_worktree.py land`; then, in a scheduled credits run (`CREDITS_RUN_ID` set), `credits_msg.py landing --part product` with the changed-file list (one repo-relative path per line) and each closeout path (the plan folder, the handoff, the reflection, the metrics file, the implementation review file); then `executor_worktree.py remove <path>`, only after the product part is in the store. Run them with the shell's working directory on the main tree, never inside the worktree. A crash between `land` and the capture leaves the worktree: capture, then remove. An interactive run (no `CREDITS_RUN_ID`) runs `land` and then `remove`, with no capture. `land_fail:busy:<pid>` is an ordering wait (let the other gate finish, then `land` again); any other `land_fail:<reason>:<rel>` names a path the main tree changed since the baseline: `sync` that path, re-edit it in the worktree, then `land` again (the `tools/executor_worktree.py` docstring). If the project ran on the main tree, record the no-op basis; a scheduled main-tree run still runs the capture (main tree, no land). | orchestrator | Landed main tree with the worktree removed (or the no-op basis in this `task.md` row) | `python tools/executor_worktree.py land {worktree} *> {{RECEIPTS_DIR}}/worktree-land.txt; $code=$LASTEXITCODE; Get-Content {{RECEIPTS_DIR}}/worktree-land.txt; if ($code -ne 0) { exit $code }; if ($env:CREDITS_RUN_ID) { python tools/credits_msg.py landing --part product --changed-files {changed-files-list} --closeout docs/execution/plans/{date}-{project-slug}/ --closeout {handoff-file} --closeout {reflection-file} --closeout docs/execution/metrics.md --closeout {review-file} *> {{RECEIPTS_DIR}}/landing-product.txt; $code=$LASTEXITCODE; Get-Content {{RECEIPTS_DIR}}/landing-product.txt; if ($code -ne 0) { exit $code } }; python tools/executor_worktree.py remove {worktree} *> {{RECEIPTS_DIR}}/worktree-remove.txt; $code=$LASTEXITCODE; Get-Content {{RECEIPTS_DIR}}/worktree-remove.txt; exit $code` | H2-3b | shared | `land_ok`, the capture line (scheduled run) and `worktree_removed` lines pasted in the handoff, or this `task.md` row for the no-op | `coordinator` | `[ ]` |
| H2-4 | Run complete closeout structural, handoff, approval, and reflection checks; under a `run_parameters` block, at the structural stage (`completion-preflight/SKILL.md` §Stages; pending set `{H2-4, H2-5, COMMIT, H2-6}`). | tester | Passing completion-preflight receipt | `python tools/lint_task_contract.py --task docs/execution/plans/{date}-{project-slug}/task.md *> {{RECEIPTS_DIR}}/closeout-preflight.txt; $code=$LASTEXITCODE; Get-Content {{RECEIPTS_DIR}}/closeout-preflight.txt; exit $code` | H2-3c | shared | Closeout receipt | `coordinator` | `[ ]` |
| H2-5 | Draft the commit manifest and conventional messages (no AI attribution trailer), then run both validators with `--stage readiness` while this row is still pending (pending set `{H2-5, COMMIT, H2-6}`); mark `[x]` only after the stage passes. Readiness is the `COMMIT` row's condition. | orchestrator | Fresh nonempty draft | `python -c "import pathlib; pathlib.Path('{{RECEIPTS_DIR}}/commit-draft.txt').write_text('feat: <slug>\\n', encoding='utf-8')" *> {{RECEIPTS_DIR}}/commit-draft-write.txt; $code=$LASTEXITCODE; Get-Content {{RECEIPTS_DIR}}/commit-draft.txt; exit $code` | H2-4 | shared | Commit-message draft | `coordinator` | `[ ]` |
| COMMIT | Commit the closeout under `commit_exec: true` with a verified `exec_commit` grant: `tools/commit_batch.py` from the H2-5 manifest, in `COMMIT_RULE` order (`test:` red files, one `feat`/`fix` per MEU, `docs(build-plan):`, the closeout `docs(<slug>):`); it verifies the count and the order and rejects an AI attribution trailer. Never push. `[x] n/a` under `commit_exec: false`, where H2-5's draft goes to the human. | orchestrator | Reconciled commit ops (or the n/a basis in this row) | `{commit_batch.py command for the H2-5 manifest}` | H2-5 | shared | Commit SHAs in the handoff | `coordinator` | `[ ]` |
| H2-6 | Finalize, the last row. In **both** `task.md` and `implementation-plan.md` write `COMMIT` `[x]`, this row `[x]`, `status: "complete"` and `stop_gate: "released:done"`; under `commit_exec: true`, commit those two files as one packet under the `finalize` grant. This row's `[x]` is provisional until the finalize op is `reconciled` (under `commit_exec: false`, until the final audit's receipt exists). Nothing after this row edits `task.md`. | orchestrator | Finalized plan files | `{commit_batch.py finalize command, or the --stage final check}` | COMMIT | shared | Finalize commit SHA (or the audit receipt) | `coordinator` | `[ ]` |

**Terminal steps (not rows).** After H2-6, run the final audit,
`tools/run_parameters.py final --produce --plan {YYYY-MM-DD}-{project-slug}`, in the main tree;
in a scheduled credits run, then run `credits_msg.py landing --part closeout`, and the monitor
seals the run (`final --seal`). Both steps write to the authority store and never to this file;
DONE is the audit's predicate, not the status string.

### Status Legend

| Symbol | Meaning |
|--------|---------|
| `[ ]` | Not started |
| `[/]` | In progress |
| `[x]` | Complete |
| `[B]` | Blocked — evidence-gated (closed reason list + pasted error; must link follow-up) |

### Evidence-First & Sequencing Rules

Evidence records follow `.agent/docs/output-evidence-policy.md`; raw receipts are working
data. Each completed row points to durable pasted observations. Update domain-specific
H1-3/H1-4 commands from PROFILE D6/D9 before execution. Replace all placeholder commands,
including the review cap, and preserve exact command status after receipt reads. No stop
hook is installed by this template; a future adapter must declare/test arming and release.


- **Evidence-first completion:** a row is `[x]` only when its deliverable exists and the handoff/walkthrough carries the evidence bundle (AGENTS.md §Execution Contract).
- **The review barrier resolves the old reflection↔review cycle:** the handoff (H1-6) is created *before* the review (it is the review's input); the reflection/metrics (H2) are created *after* `approved` so they can record the verdict. Do not create H2 artifacts during H1, and do not dispatch the review (H1-7) before the handoff exists.
- **Self-review prohibition:** the implementing agent dispatches and collects the H1-7 review; it never authors the `approved` verdict itself (AGENTS.md §Execution Contract).
- **`[B]` is evidence-gated:** valid ONLY for (a) a reproduced *external* error, (b) a missing dependency/credential/permission, or (c) a human-decision gate — each with a linked follow-up and, for (a)/(b), a row-bound `### B-<row-id>` block with command, nonzero exit and pasted decisive error as `evidence.v1`; decisions need a durable decision link. The row cites `B-<row-id>` and `follow-up [label](target)`. Subjective reasons ("too complex", "no time", "out of scope", "later") are invalid; no error artifact ⇒ not blocked ⇒ keep working (AGENTS.md §Execution Contract).
- **Dispatching the H1-7 review is a blocking step, not a turn boundary:** continue to H2 in the same pass once the `approved` verdict file lands. The only sanctioned turn-enders are DONE, review cap, reviewer unavailable, or human decision; compaction continues (AGENTS.md §Execution Contract).
