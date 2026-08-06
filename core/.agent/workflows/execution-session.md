---
description: Structured execution + meta-reflection workflow for daily build sessions. Ensures TDD discipline, handoff quality, and iterative prompt improvement.
---

# Execution Session Workflow

Executable examples follow `.agent/docs/output-evidence-policy.md`; that file is the
sole authority for native RTK versus exact `rtk proxy` routing.

Use this workflow at the start of each build session. It orchestrates three phases: **Plan → Execute → Reflect** — creating a feedback loop that makes each successive session faster and higher quality.

Artifact naming conventions:

- `docs/execution/plans/{YYYY-MM-DD}-{project-slug}/implementation-plan.md`
- `docs/execution/plans/{YYYY-MM-DD}-{project-slug}/task.md`
- If a project is replanned on the same day, append `-v2`, `-v3`, etc. to the folder name.

// turbo-all
// NOTE: turbo-all sets SafeToAutoRun=true for non-destructive commands (rg, Get-Content, etc.).
// It does NOT override AGENTS.md §Commits: "Never auto-commit." Git commit/push still requires explicit user direction.

## Prerequisites

- Read `AGENTS.md`
- Read `.agent/context/current-focus.md` for active phase
- Read `.agent/context/meu-status.yaml` for MEU scope (see `.agent/skills/meu-status/SKILL.md`)

## Context Tool Decision Gate (Before Planning or Execution)

Before Step 1, follow `.agent/docs/context-tool-decision-gate.md`. Inventory Graphify,
Graphify Research, and Headroom, flag eligible token-savings opportunities, and obtain
the direct human decision before planning starts. Before Step 4, re-evaluate the
execution scope; reuse the planning decision only when its recorded phase explicitly
covers execution and eligibility has not changed. Otherwise obtain a new
`USER_EXPLICIT` `use` or `accepted_loss` decision. Record `not_applicable` when no tool
is eligible.

## Steps

### 1. Create Project Plan

Run the `/create-plan` workflow (`.agent/workflows/create-plan.md`). This replaces per-session prompt drafting — the agent discovers what's done, identifies what's next, runs a spec-sufficiency gate, resolves thin specs via research when needed, and scopes a coherent project.

### 2. Check Previous Reflections

Read the most recent reflection file from `docs/execution/reflections/` (sort by `LastWriteTime` descending to find the latest, since multiple same-day reflections sort by slug). Apply any rules from its "Next Session Design Rules" section to today's planning. Call out which rules you're applying so the human can verify.

### 3. Planning Phase (PLANNING Mode)

> Steps 1-3 happen as part of the `/create-plan` workflow.
> Tool names below are capability placeholders — see `.agent/docs/harness-profiles.md` for the per-harness substitution table (`read_tool`, `shell_tool`, `end_turn_signal`).

The orchestrating agent will:

1. Enter **PLANNING mode** (mode marker only — a `task_boundary` call on harnesses that have one, otherwise track mode in your own working notes; see harness-profiles.md)
2. Discover progress from handoffs + the MEU status SSOT using the canonical exact-receipt form for the `tools/meu_status.py stats` argv
3. Scope the next project from pending build-plan MEUs
4. Resolve under-specified requirements via local canonical docs + targeted web research before finalizing the FIC
5. Generate `implementation-plan.md` and `task.md` in the project folder
6. Auto-dispatch `/plan-critical-review` via the independent-reviewer chain (Codex GPT-5.6-sol → Gemini surface → headless Claude last-resort; `.agent/docs/model-routing.md`)
7. Loop corrections until APPROVED (or HARD STOP at 3-round cap)
8. On `approved`: continue to Step 4 per your harness's `plan_to_exec_gate` flag (`.agent/docs/harness-profiles.md`) — `reviewer-auto` continues immediately; `plan_to_exec_gate: human` (the primary-driver default) ends the turn and waits for the user's explicit next chat message before Step 4 (`create-plan.md` §5c, `GUARDRAILS.md` SIGN 1)

> **Note:** The `/create-plan` workflow now auto-dispatches plan critical review.
> The human no longer needs to manually invoke `/plan-critical-review`.
> See `create-plan.md` Step 5 for the auto-review loop details.

**Plan Location** (established during `/create-plan` workflow):

The `/create-plan` workflow writes `implementation-plan.md` and `task.md` directly to `docs/execution/plans/{YYYY-MM-DD}-{project-slug}/`. This is the single source of truth — all revisions happen here. No copy step is needed.

> **Why here?** Brain folders are per-conversation and not version-controlled. Writing directly to `docs/execution/plans/` preserves plans in git and allows cross-session comparison of planning quality.

### 4. Execute the Approved Plan

Follow the plan **exactly**. The prompt contains:
- **Session Goal** — what success looks like
- **Phase A** — any scaffold or infrastructure setup
- **Phase B** — MEU TDD work (FIC → Red → Green → Quality → Handoff)
- **Phase C** — Auto-dispatched external-reviewer validation (Codex GPT-5.6-sol primary; chain in `.agent/docs/model-routing.md`)
- **Guardrails** — hard scope limits

Before each row, validate its `depends_on` IDs against completed task rows. Execute its
`context_strategy` as follows: `shared` continues normally; `compact_continue` verifies
the named durable output, compacts, then re-reads `task.md` followed by that output;
`isolated` uses a fresh worker only when the resolved harness exposes an authorized
`fresh_worker` mechanism. Otherwise it degrades to `compact_continue`. Metadata is not
permission to spawn. Do not reload completed independent rows wholesale after recovery.

> **In-harness delegation.** When `fresh_worker` resolves (Cursor `.cursor/agents/` or Claude Code
> `.claude/agents/`), route the `isolated`/mechanical/verification decision through
> [`.agent/skills/subagent-delegation/SKILL.md`](../skills/subagent-delegation/SKILL.md) — it owns
> the detection, decision table (incl. the never-delegate categories), dispatch-prompt contract,
> and result-acceptance rules for `{{PROJECT_NAME}}-builder`/`{{PROJECT_NAME}}-verifier`.

#### After compaction

1. Re-read the canonical project `task.md`.
2. Read the current row's relevant durable output.
3. Load only the next unchecked row's direct inputs; do not reconstruct state from the
   transcript or reload completed independent rows wholesale.

Key rules during execution:

> ⚠️ **P0 Terminal Pre-Flight** — Before the first shell command (your harness `shell_tool`, e.g. `run_command`/`Bash`) in this phase, invoke
> `.agent/skills/terminal-preflight/SKILL.md` and confirm all 4 checklist items.
> See `AGENTS.md §PRIORITY 0` for the redirect pattern.
- Follow `.agent/workflows/tdd-implementation.md` for all TDD work
- Follow `.agent/workflows/meu-handoff.md` for handoff creation
- **Execute all MEUs in the approved project plan**, completing each MEU's TDD cycle before starting the next
- **Keep the project handoff set explicit**: `implementation-plan.md` and `task.md`
  list `.agent/context/handoffs/{date}-{project-slug}-{MEU-ID}-handoff.md` for each
  product MEU. A non-product `meus: []` project lists one project handoff at
  `.agent/context/handoffs/{date}-{project-slug}-handoff.md`. The execution review
  loads that complete set instead of only the latest handoff.
- **Keep review continuity explicit**: for a given project plan folder, maintain one rolling `-plan-critical-review.md` file for plan review passes and one rolling `-implementation-critical-review.md` file for project-level implementation critique/recheck passes
- If a new spec gap appears mid-execution, stop coding, return to planning/research, update the plan with the source-backed resolution, and get approval on the revised plan before continuing
- **Do not auto-commit** — propose conventional commit messages to the human instead; proposed messages must not include AI attribution trailers or generated-by statements such as `Co-Authored-By: Claude`
- **Recite remaining work (anti-drift, Manus pattern):** after each MEU handoff AND at the start of the closeout (Step 5), re-read `task.md` and restate the still-unchecked (`[ ]`/`[/]`) rows in one line before starting the next item. This pushes the live task state into recent attention so the closeout list does not drift out of context as tool output accumulates.

### 4b. Pre-Handoff Self-Review Protocol

> **Why this step exists**: Analysis of 7 critical review handoffs (37+ review passes) revealed 10 recurring patterns that caused 4-11 passes per project. This protocol catches those patterns before submission, targeting 2-3 passes.

Before declaring any MEU "ready for review" or writing completion claims in the handoff:

1. **Claim-to-State Verification** (Pattern: claim-to-state drift, 7/7 reviews)
   - For each AC marked "met", `rg` the actual code for the specific behavior. Quote file:line.
   - If the handoff says "all N ACs covered", verify every single one against file state — not memory.
   - If the residual risk section acknowledges known gaps, the conclusion MUST NOT say "implementation complete."

2. **Evidence Freshness — MUST BE LAST** (Pattern: evidence staleness, 6/7 reviews)
   - This step must be the LAST action before submitting the handoff. Running it before fix-generalization or cross-doc sweeps creates the staleness it aims to prevent.
   - Re-run ALL validation commands (`pytest`, `pyright`, `ruff`, `eslint`, `vitest`) _after_ all other self-review fixes are applied.
   - **Evidence Command Manifest**: Record the EXACT commands used (verbatim, including all flags and scope), not just results. Reject evidence from cached/partial runs (`--lf`, `-k`, unit-only markers when integration should also run).
   - Paste the fresh output counts into the handoff. Counts from earlier in the session are stale.

3. **Fix-General-Not-Specific** (Pattern: fix-specific-not-general, meta-pattern)
   - When fixing any finding, categorize it (e.g., "missing error mapping", "stale evidence count").
   - Run `rg` for the same pattern across all similar files/routes/modules.
   - Document: "Checked N similar locations, found M additional instances, fixed all."

4. **Error Mapping Sweep** (Pattern: error mapping gaps, 3/7 reviews)
   - For API routes: verify every write-adjacent route maps `NotFoundError → 404`, `BusinessRuleError → 409`, `ValueError → 422`.
   - For MCP tools: verify every handler maps domain exceptions to proper MCP error responses.

5. **Cross-Reference Sweep** (Pattern: canonical doc contradiction, 3/7 reviews)
   - If you changed an architectural pattern (e.g., token model, auth flow, DI wiring), use the canonical exact-evidence search receipt across `docs/build-plan/`, `docs/execution/`, and `.agent/`.
   - All references must agree with the new pattern. Update any that don't.

6. **Project Artifact Completeness** (Pattern: artifact incompleteness, 6/7 reviews)
   - Verify `task.md` items match actual completion state.
   - Verify the SSOT drift check passes by routing the `tools/meu_status.py render --check` argv through the canonical exact-receipt form.
   - Do NOT create reflection/metrics artifacts until AFTER validation completes.

7. **Pre-Completion Sweep** (Pattern: count-bearing string drift, meta-review RULE-2)
   - Search all count-bearing strings (test counts, "passing", "FAIL_TO_PASS") across ALL touched handoffs/docs using an exact unfiltered receipt.
   - Cross-check every file listed in the handoff evidence table exists on disk: `Test-Path <path>` for each.
   - Run `pre-handoff-review` SKILL (`.agent/skills/pre-handoff-review/SKILL.md`) — 10-pattern self-check.
   - Only after all three sub-steps pass: mark complete and set `corrections_applied`.

> [!IMPORTANT]
> **Compact at the MEU boundary (after the handoff is on disk).** Once this MEU's handoff is written and the self-review above passes — and *only* then — compact the transcript via your harness's `context_compaction` capability (`.agent/docs/harness-profiles.md`) before starting the next MEU. The handoff + `task.md` ARE the durable state, so compaction loses nothing that matters: **compaction is lossy, files are not.** Compact proactively here while headroom remains (good summary) rather than letting auto-compaction fire at the limit (degraded summary). Re-read `task.md` afterward before acting. If `context_compaction` is `none`, skip. See [`.agent/docs/context-compression.md`](../docs/context-compression.md) §Context Compaction.

### 4c. Auto-Dispatch Execution Critical Review

> [!IMPORTANT]
> **After Step 4b completes, the agent auto-dispatches `/execution-critical-review`**
> to an external CLI reviewer and loops until APPROVED or the round cap is reached.
> The human no longer needs to manually invoke `/execution-critical-review`.

Follow `.agent/skills/cli-dispatch/SKILL.md` to dispatch `/execution-critical-review`:

**Reviewer Agent Priority** (canonical chain in [`.agent/docs/model-routing.md`](../docs/model-routing.md) §Independent-reviewer chain):
1. **Codex CLI (GPT-5.6-sol)** — Primary (`-c model_reasoning_effort=medium` routine; `high` for risk paths / contract surfaces / concurrency / security — see `cli-dispatch/SKILL.md` §Reviewer Effort Policy)
2. **Gemini 3.5** — Secondary, **surface-level reviews only** (never deep-infra/troubleshooting)
3. **headless `claude -p` (Opus 5, fresh isolated context)** — Last resort when Codex rate-limited AND the change is too deep for Gemini (`--effort high --permission-mode bypassPermissions`; flag verdict as same-vendor; `max` only for tagged deep sub-reviews)
4. **All rungs rate-limited/unavailable** — HARD STOP (never self-review)

**Correction Loop:**
- If `changes_required`: read findings, apply code/test corrections, re-run quality gates, re-dispatch
- If `approved`: **continue immediately to Step 5 in the same turn** — the 4c→5 boundary is NOT a stop point
- **Round cap: 6 rounds** — HARD STOP with TL;DR summary, wait for human "continue review loop"
- On human resume: continue loop (round 7+) until APPROVED

> [!CAUTION]
> **Steps 4 → 4b → 4c → 5 → 6 → 7 are ONE continuous turn — there is no seam.** The `approved` verdict and writing the reflection/metrics belong to the same pass; the boundary between them is NOT a stopping point, NOT a "natural pause", and NOT a place to offer the user a choice. The reflection and metrics are reversible work inside an already-approved plan and need no permission (`AGENTS.md` §Hard Gates). **The following are VIOLATIONS, not courtesies** — if you catch yourself composing any of them, that urge is the bug:
> - ❌ "Want me to continue with the reflection/closeout, or handle it in a separate session?"
> - ❌ "Implementation is approved — shall I proceed to the reflection?"
> - ❌ "This looks like a good stopping point. Let me know if you'd like me to continue."
> - ❌ Any progress-report hand-back after a sub-milestone (review approved, gate passed) that is not one of the five sanctioned turn-enders.
>
> The ONLY sanctioned turn-enders are the five in `AGENTS.md` §Execution Contract: DONE, execution-review round cap, all reviewer rungs rate-limited, ~50% context checkpoint (handoff → compact → continue; not a hand-back — a turn-ender only if `context_compaction` is `none`), human-decision gate.

> [!CAUTION]
> **Do NOT auto-commit after execution review approval.** Present proposed commit
> messages to the human and wait for explicit commit direction. Do not include
> AI attribution trailers or generated-by statements in proposed commit text.

**Edge cases** (same as `create-plan.md` §5e):
- Reviewer asks questions → auto-answer from local canon or HARD STOP for human
- Rate limit mid-loop → fallback reviewer or HARD STOP with timer
- Session crash → review file on disk is the resumption checkpoint

### 5. Meta-Reflection (Post-Execution)

After validation has completed for the project's MEU handoff set, create the reflection file at `docs/execution/reflections/{YYYY-MM-DD}-{project-slug}-reflection.md`.

> **Start from** [`docs/execution/reflections/TEMPLATE.md`](file:///{{PROJECT_ROOT}}/docs/execution/reflections/TEMPLATE.md) (v2.0)

Structure the reflection with these sections:

#### 5a. Execution Trace
Answer 12 structured questions across three logs:
- **Friction Log** (5 questions): What was slow, ambiguous, unnecessary, missing, improvised?
- **Quality Signal Log** (3 questions): Which tests caught real bugs, which were trivial, did static analysis add value?
- **Workflow Signal Log** (4 questions): Was the FIC useful, was the handoff right-sized, how many tool calls, and which rows were delegated to a subagent (harness + model) and did any delegated result need rework?

#### 5b. Pattern Extraction
From the friction log, categorize findings into:
- **Patterns to KEEP** — 2–3 practices that worked well
- **Patterns to DROP** — 1–2 practices that were ceremony without payoff
- **Patterns to ADD** — 1–2 gaps that caused problems
- **Calibration Adjustment** — was the time estimate accurate?

#### 5c. Next Session Design Rules
Write 3–5 concrete rules for the next session's plan, formatted as:
```
RULE-{N}: {description}
SOURCE: {which signal led to this}
EXAMPLE: {before/after}
```

#### 5d. Next Session Outline
Write a 10-line outline for the next session's plan:
- Which MEUs to target
- What scaffold changes are needed
- Which patterns from today's reflection to bake in
- Codex validation scope

#### 5e. Update Metrics

Append a row to `docs/execution/metrics.md` using the existing table format:

```markdown
| {YYYY-MM-DD} | MEU-{N} | {count} | {duration} | {count} | {count} | {X}/7 | {N}% | {duration} | {notes} |
```

The columns are: Date, MEU(s), Tool Calls, Time to First Green, Tests Added, Codex Findings, Handoff Score (X/7), Rule Adherence (%), Prompt→Commit (min), Notes.

### 6. Notify Human

> [!CAUTION]
> **Completion gate + recency anchor.** Before notifying, read (your harness `read_tool`) `task.md` and verify every row is `[x]` (or a valid `[B]`). If any row is `[ ]` or `[/]`, complete it first — do not skip, do not defer to "a separate session". Reaching this step with unchecked rows does NOT authorize a stop; it authorizes *finishing them*. The only sanctioned turn-enders remain the five in `AGENTS.md` §Execution Contract.

Present the human with:
1. Completion summary (MEUs done, tests passing, proposed commit messages)
2. Link to the reflection file for review
3. Draft outline for the next session (used by `/create-plan` workflow)

> [!NOTE]
> **Prose is probabilistic; a hook is deterministic.** This gate and the Step 4c anti-stop rule *shift* the model's stop/continue choice but cannot guarantee it — the RLHF deference prior will sometimes win the sampling roll regardless of wording. The durable backstop is a **harness-level Stop hook** that blocks end-of-turn until `task.md` has no `[ ]`/`[/]` rows and the closeout artifacts exist on disk. That hook lives in the harness config (e.g. Antigravity's stop-hook, or Claude Code's `settings.json` hook — see `.agent/docs/harness-profiles.md` for your harness's mechanism), NOT in this workflow file — out of scope here, but the recommended complement. Guard it with a consecutive-block / `stop_hook_active` loop-breaker so a genuinely-blocked turn can still end.

### 8. Completion Timestamp (Mandatory Exit Gate)

> [!IMPORTANT]
> **Context-rot guard.** Re-read this workflow file before proceeding.
> If you are resuming after context truncation, this step will not exist in your context unless you re-read.

The **very last line** of the agent's chat response must be the timestamp skill output, copied verbatim.

This is a hard exit requirement for every `/execution-session` response, including checkpoints, Codex-validation handoffs, and final completion summaries.

Required sequence:

1. Re-read this workflow file to confirm all prior steps are complete.
2. Invoke the timestamp skill by reading `.agent/skills/timestamp/SKILL.md`.
3. Run the stamp script with the Windows redirect-to-file pattern:

```powershell
# // turbo
rtk proxy uv run python .agent/skills/timestamp/scripts/stamp.py *> {{RECEIPTS_DIR}}/stamp.txt; $code=$LASTEXITCODE; Get-Content {{RECEIPTS_DIR}}/stamp.txt; exit $code
```

4. Read `{{RECEIPTS_DIR}}/stamp.txt` with the file viewer.
5. Copy the file's single output line verbatim as the final chat line.

No text, bullets, caveats, or sign-off may appear after the timestamp line.

Compressed variant for checkpoints:

```text
Checkpoint saved for <project-slug>. Status: <blocked|ready-for-review|complete>. Key evidence: <one sentence>.
🕐 Completed: YYYY-MM-DD HH:MM (TZ)
```

The compressed variant still requires invoking the timestamp skill and copying its real output verbatim for the last line.

## Session Lifecycle Summary

```
┌─────────────────────────────────────────────────────┐
│  /create-plan workflow                              │
│  → reads handoffs, meu-status SSOT, build-plan      │
│  → scopes project, generates plan                   │
│  → auto-dispatches /plan-critical-review            │
│  → loops corrections until APPROVED                 │
└───────────┬─────────────────────────────────────────┘
            ▼
┌─────────────────────────────────────────────────────┐
│  EXECUTION Mode (per MEU)                            │
│  → TDD cycle → handoff → registry update            │
│  → auto-dispatches /execution-critical-review       │
│  → loops corrections until APPROVED                 │
└───────────┬─────────────────────────────────────────┘
            ▼
┌─────────────────────────────────────────────────────┐
│  Meta-reflection + session digest                   │
│  → friction/quality/workflow logs                   │
│  → pattern extraction → design rules                │
│  → reflection saved to docs/execution/reflections/  │
│  → session digest at .agent/context/sessions/       │
│  → metrics updated                                  │
└─────────────────────────────────────────────────────┘
```

## Exit Criteria

- [ ] Plan archived to `docs/execution/plans/{YYYY-MM-DD}-{project-slug}/`
- [ ] All project plan steps completed
- [ ] Handoff artifact(s) created at `.agent/context/handoffs/`
- [ ] MEU-status indexes updated for completed MEUs using canonical exact receipts for the target-bound `tools/meu_status.py update MEU-{N} approved` and `tools/meu_status.py render` argv, plus `.agent/context/current-focus.md`
- [ ] Reflection file created at `docs/execution/reflections/`
- [ ] Metrics table updated
- [ ] Session digest created at `.agent/context/sessions/{conversation-id}/digest.md`
- [ ] Proposed commit messages presented to human (do NOT auto-commit; no AI attribution trailers)
