---
description: Delegate /create-plan Steps 1-4 to Claude Code CLI (`coordinator` or `architecture_single_shot`) for plan generation, then run the Codex review/correction loop from the in-harness orchestrator (`coordinator` class). Use when the planning task benefits from `architecture_single_shot`'s deeper reasoning on the Claude CLI planner, or when the orchestrator wants to reserve context for execution.
---

# Delegated Plan Creation Workflow

Delegate plan generation (Steps 1-4 of `/create-plan`) to Claude Code CLI using `coordinator` or `architecture_single_shot`, then handle the Codex plan-critical-review correction loop from the in-harness orchestrator (`coordinator` class). `architecture_single_shot` applies only to the *Claude CLI planner* spawn for complex plans — not as the orchestrator default. This separates expensive planning from mechanical review corrections. Class→snapshot bindings live in the live registry home you instantiate (see `.agent/INSTANTIATE.md`).

## When to Use

- The planning task is complex enough to benefit from `architecture_single_shot`'s deeper reasoning on the Claude CLI planner
- The orchestrator wants to preserve context window for execution
- The user explicitly requests delegated planning ("use architecture_single_shot to create the plan")
- Session grouping is already done — the MEU scope and project slug are known

## Prerequisites

- Session grouping exists (`.agent/context/grouping/` has the relevant file)
- MEU scope is defined (which MEUs, which build-plan sections)
- Project slug is determined

## Architecture

```
Phase 1: Claude CLI (`architecture_single_shot` / `coordinator`) — Planning
  └── Reads context files, build plan, templates
  └── Generates implementation-plan.md + task.md
  └── STOPS (does NOT dispatch Codex or start execution)

Phase 2: Orchestrator (`coordinator` class; primary driver per `.agent/docs/harness-profiles.md`) — Review Loop
  └── Dispatches `independent_reviewer` for /plan-critical-review
  └── Reads verdict, applies corrections if needed
  └── Re-dispatches until approved or round cap (3)

Phase 3: Orchestrator or User — Execution
  └── Plan is ready for /tdd-implementation or /execution-session
```

> [!IMPORTANT]
> **The planner does NOT dispatch Codex.** This is the key difference from standard `/create-plan`. The orchestrator handles the review loop to save planner usage limits and because corrections don't require cutting-edge reasoning.

---

## Step 1: Pre-Flight

### 1a. CLI Version Check (once per session)

```powershell
# Check and update Claude CLI
claude --version *> {{RECEIPTS_DIR}}/dispatch/claude-version.txt
claude update *> {{RECEIPTS_DIR}}/dispatch/claude-update.txt 2>&1
Get-Content {{RECEIPTS_DIR}}/dispatch/claude-update.txt | Select-Object -Last 5

# Check and update Codex CLI (needed for Phase 2)
codex --version *> {{RECEIPTS_DIR}}/dispatch/codex-version.txt
codex update *> {{RECEIPTS_DIR}}/dispatch/codex-update.txt 2>&1
Get-Content {{RECEIPTS_DIR}}/dispatch/codex-update.txt | Select-Object -Last 5
```

### 1b. Auth Detection

Detect billing mode for both Claude and Codex (see `cli-dispatch/SKILL.md` §Authentication).

### 1c. Ensure Dispatch Directory

```powershell
New-Item -ItemType Directory -Force -Path {{RECEIPTS_DIR}}/dispatch | Out-Null
```

---

## Step 2: Write the Planning Prompt

Write a comprehensive prompt file to `{{RECEIPTS_DIR}}/dispatch/prompt.txt`. The prompt must be self-contained — the planner has no prior context.

### Required Prompt Sections

```markdown
# /create-plan Dispatch — {MEU list} ({Project Title})

You are performing the `/create-plan` workflow for the {{PROJECT_NAME_TITLE}} project.
Your task is to execute Steps 1 through 4 (planning ONLY) and then STOP.
Do NOT proceed to Step 5 (Codex review) or Step 6 (execution).

## CRITICAL STOP CONDITION

**STOP after generating implementation-plan.md and task.md.**
Report the file paths and end your session. The orchestrator handles
the Codex review loop separately.

## Project Scope

- **Project slug:** `{YYYY-MM-DD}-{project-slug}`
- **MEUs:** {list with slugs}
- **Build plan source:** `docs/build-plan/{file}.md`
- **Session grouping source:** `.agent/context/grouping/{file}.md`

{Include MEU summaries from the grouping file — layer, size, deps, why grouped}

## Required Files to Read (in order)

1. `AGENTS.md`
2. `.agent/context/current-focus.md`
3. `.agent/context/known-issues.md`
4. `.agent/docs/emerging-standards.md`
5. `docs/build-plan/{target-file}.md`
6. `docs/build-plan/build-priority-matrix.md`
7. `.agent/context/grouping/{grouping-file}.md`
8. `docs/execution/plans/PLAN-TEMPLATE.md` (MUST view before writing)
9. `docs/execution/plans/TASK-TEMPLATE.md` (MUST view before writing)

## Steps 1-2: Discovery

{Include MEU status commands}

## Step 4: Generate Plan

{Include project folder path, naming conventions, plan requirements}

## Rules

- Follow the terminal redirect pattern for all commands
- Use `uv run` for Python tools
- Do NOT create or modify any production code
- Do NOT dispatch Codex or any reviewer
- Do NOT proceed to execution
- Read templates before writing plan files
```

> [!CAUTION]
> **Prompt > 2KB — use stdin pipe.** The planning prompt will always exceed 2KB.
> Use `Get-Content prompt.txt | claude -p ...` (NOT positional arg).

---

## Step 3: Dispatch the Planner

### Model Selection

| Class | Resolve (`claude-p`) | Effort | Budget | Use When |
|-------|----------|--------|--------|----------|
| **`architecture_single_shot`** | `$(resolve architecture_single_shot -Harness claude-p -Project <project-root>)` (when bound) | `--effort high` | generous | Complex multi-MEU plans, architecture-heavy, spec gaps |
| **`coordinator`** | `$(resolve coordinator -Harness claude-p -Project <project-root>)` | `--effort high` | moderate | Standard plans, single-MEU, well-specified |

> Per-class price bands and empirical budget guidance live in the registry catalog (`price_band`, `price_note`) — do not restate dollar figures here.
>
> **`architecture_single_shot` at `--effort high` burns more subscription quota** than `coordinator` at the same effort. Use `--effort medium` for cost savings if the plan scope is well-defined.

### Dispatch Command

```powershell
# Delete stale output
Remove-Item -Force -ErrorAction SilentlyContinue {{RECEIPTS_DIR}}/dispatch/claude-plan-output.txt

# Resolve planner class → snapshot (live registry home; see .agent/INSTANTIATE.md)
# `-Project` is what makes the working project's overlay apply; without it the
# answer comes from global policy even where this project has tightened the
# class. Resolution is a prerequisite, not a step: a failure must stop the
# dispatch rather than launch a planner with an empty `--model`.
$ErrorActionPreference = 'Stop'
Import-Module <registry-home>/tools/ModelRegistry.psm1 -Force
$plannerClass = "coordinator"  # complex plans: architecture_single_shot when bound on this harness
$plannerSlug = resolve $plannerClass -Harness claude-p -Project <project-root>
if (-not $plannerSlug) { throw "resolve returned no slug for $plannerClass" }

# Dispatch (coordinator example — swap class when architecture_single_shot is bound)
Get-Content {{RECEIPTS_DIR}}/dispatch/prompt.txt | claude -p `
  --model $plannerSlug `
  --effort high `
  --permission-mode bypassPermissions `
  --output-format json `
  --max-turns 80 `
  --max-budget-usd 35 `
  *> {{RECEIPTS_DIR}}/dispatch/claude-plan-output.txt
```

**Parameters:**
- `--permission-mode bypassPermissions` — planner needs full file access (reads ~10+ files, writes plan files, runs MEU status commands)
- `--max-turns 80` — generous for Steps 1-4 (empirical: 26 turns for 2-MEU plan)
- `--max-budget-usd` — hard cap; size per class band in registry catalog (`architecture_single_shot` needs a generous cap)
- `-Project` — resolves against this project's accepted overlay, not global policy alone
- Working directory: set via `Cwd` in `run_command` (Claude has no `-C` flag)

### Background Dispatch

```powershell
# Send to background (planning takes 5-15 minutes)
# WaitMsBeforeAsync: 500 (background immediately)
# Set a 5-minute wakeup timer
```

### Parse Output

```powershell
$raw = Get-Content {{RECEIPTS_DIR}}/dispatch/claude-plan-output.txt -Encoding Unicode -Raw
$json = $raw | ConvertFrom-Json
$result = $json.result       # Final message (may be empty on budget exceeded)
$turns = $json.num_turns     # Turns used
$isError = $json.is_error    # true if budget/turn limit hit
```

> [!NOTE]
> **`is_error: true` with budget exceeded is NOT a failure** if the plan files exist.
> Check for `implementation-plan.md` and `task.md` in the project folder regardless of exit status.

---

## Step 4: Verify Plan Files

After the planner finishes (or exceeds budget), verify the deliverables:

```powershell
$planDir = "docs/execution/plans/{YYYY-MM-DD}-{project-slug}"
if (Test-Path $planDir) {
    Get-ChildItem $planDir | ForEach-Object { "$($_.Name): $($_.Length) bytes" }
} else {
    "FAILED: Plan directory not created"
}
```

**Required files:**
- `implementation-plan.md` (expected: 15-30KB for 2-MEU plan)
- `task.md` (expected: 10-20KB)

If either file is missing, the dispatch failed — check the log file and retry.

---

## Step 5: Orchestrator-Driven Review Loop

The orchestrator (the primary driver, per `.agent/docs/harness-profiles.md`) now handles the Codex plan-critical-review loop.

### 5a. Open the loop, then dispatch Codex R1

The round cap in 5c is enforced by the ledger, not by the orchestrator remembering to
count. Open the loop once, before R1:

```powershell
$LOOP_ID = "planreview-{project-slug}-{YYYY-MM-DD}"
python tools/review_ledger.py begin `
  --loop-id $LOOP_ID `
  --review-mode plan `
  --producer "<the agent that wrote the plan>"
```

`--review-mode plan` is what sets the cap of 3 referenced in 5c — the number lives in
the ledger, so there is one place to change it and no prose copy to drift.

```powershell
powershell -NoProfile -File tools/Invoke-CodexDispatch.ps1 `
  -Mode ReviewReadOnly `
  -LoopId $LOOP_ID `
  -Kind plan `
  -ReasoningEffort high `
  -OutputSchema .agent/schemas/review-verdict.schema.v2.json `
  -DispatchId "{project-slug}-planreview-r1" `
  -Force `
  -PromptText "Perform /plan-critical-review for {project-slug}. Read .agent/workflows/plan-critical-review.md for the full protocol. Review targets: docs/execution/plans/{YYYY-MM-DD}-{project-slug}/implementation-plan.md and docs/execution/plans/{YYYY-MM-DD}-{project-slug}/task.md."

# Record the round before rendering it. An unrecorded round is one the cap never sees.
python tools/review_ledger.py record --loop-id $LOOP_ID `
  --verdict-file {{RECEIPTS_DIR}}/dispatch/{project-slug}-planreview-r1/final.json

# Render the verdict on the orchestrator side
uv run python tools/render_review_verdict.py `
  --input {{RECEIPTS_DIR}}/dispatch/{project-slug}-planreview-r1/final.json `
  --output .agent/context/handoffs/{project-slug}-plan-critical-review.md `
  --overwrite
```

> [!IMPORTANT]
> **`render_review_verdict.py` is NOT shipped** with this package (`core/MANIFEST.md`
> §Deliberately EXCLUDED). It is a presentation convenience: it turns the verdict JSON
> into the rolling review markdown. Nothing *decides* anything from its output —
> `review_ledger.py record` reads `final.json` directly, and the round cap is enforced
> at dispatch time.
>
> Until you write it, do the render by hand and keep both artifacts:
> - `final.json` stays the machine-readable verdict (what `record` validates).
> - `.agent/context/handoffs/{project-slug}-plan-critical-review.md` is still
>   **required** — it is the review file §5b reads, the one the reviewer appends each
>   round to, and the target `validate_closeout_artifacts.py --review` checks. Create it
>   from the REVIEW-TEMPLATE and paste the verdict's `verdict`, `findings`, and
>   `rationale` into it. Do **not** substitute "read the JSON" for the review file; a
>   missing review file fails the closeout checks, and `--overwrite` semantics matter
>   only to the renderer, not to the loop.

> **First review uses `high` effort** — the planner's output hasn't been reviewed yet, so treat it as a first substantive review per §Reviewer Effort Policy.

### 5b. Parse Verdict

```powershell
Get-Content .agent/context/handoffs/{project-slug}-plan-critical-review.md
```

### 5c. Correction Loop (Orchestrator Applies Fixes)

**If `changes_required`:**

1. Read findings from the review handoff file
2. Apply corrections directly to `implementation-plan.md` and/or `task.md` using file edit tools
3. Re-dispatch Codex with `medium` effort (follow-up round, corrections are mechanical):

```powershell
powershell -NoProfile -File tools/Invoke-CodexDispatch.ps1 `
  -Mode ReviewReadOnly `
  -LoopId $LOOP_ID `
  -Kind plan `
  -ReasoningEffort medium `
  -OutputSchema .agent/schemas/review-verdict.schema.v2.json `
  -DispatchId "{project-slug}-planreview-r{N}" `
  -Force `
  -PromptText "Perform /plan-critical-review ROUND {N} recheck for {project-slug}. Review targets: docs/execution/plans/{YYYY-MM-DD}-{project-slug}/implementation-plan.md and docs/execution/plans/{YYYY-MM-DD}-{project-slug}/task.md. Apply template checklist checks and confirm if prior findings have been fixed."

python tools/review_ledger.py record --loop-id $LOOP_ID `
  --verdict-file {{RECEIPTS_DIR}}/dispatch/{project-slug}-planreview-r{N}/final.json

# Render and append/overwrite the verdict on the orchestrator side
# (not shipped -- see the §5a note; by hand, append round {N}'s verdict to the same
#  rolling review file rather than creating a per-round one)
uv run python tools/render_review_verdict.py `
  --input {{RECEIPTS_DIR}}/dispatch/{project-slug}-planreview-r{N}/final.json `
  --output .agent/context/handoffs/{project-slug}-plan-critical-review.md `
  --overwrite
```

4. Repeat until `approved`, or until the dispatch exits `9` — the ledger's cap for
   `--review-mode plan` is 3 rounds, and it is enforced at dispatch time rather than by
   the orchestrator tracking `{N}` itself. Do not answer a `9` by re-running with
   `-NonReviewDispatch`; that is recorded in `status.json` as
   `ledger_gate: bypassed-non-review` and leaves the round uncounted. Read the stop kind
   in the refusal message and apply its own relief (`grant` for `budget`, `relieve` for
   `mechanism`), or escalate to a human. Round number comes from
   `review_ledger.py state --loop-id $LOOP_ID`, which is authoritative — `{N}` in the
   `-DispatchId` above is a label, not the count.

**If `approved`:**
→ Report the verdict, then branch on `plan_to_exec_gate` (`.agent/docs/harness-profiles.md`): if `human` (Claude Code / Cursor / headless / UNKNOWN — see `GUARDRAILS.md` SIGN 1, `create-plan.md` §5c), end the turn and wait for the user's explicit "start execution"/"proceed"; if `reviewer-auto` (only the legacy Antigravity *driver* profile, dormant), auto-continue straight to execution.

### 5d. Round Cap — HARD STOP

If 3 rounds without approval, present TL;DR and wait for human direction.

---

## Step 6: Report and Hand Off

Present to the user:

```
Plan approved by Codex `independent_reviewer` in {N} rounds.

Planner: {architecture_single_shot | coordinator} @ {effort} — {turns} turns
Review: {N} rounds (R1: {findings}, R2: {findings}, ...)

Plan files:
  docs/execution/plans/{slug}/implementation-plan.md
  docs/execution/plans/{slug}/task.md
Review:
  .agent/context/handoffs/{slug}-plan-critical-review.md

{if plan_to_exec_gate == human: Ready for execution. Say "start execution" to begin TDD implementation.}
{if plan_to_exec_gate == reviewer-auto: Auto-continuing to execution.}
```

Per the canonical gate rule (`.agent/docs/harness-profiles.md`, `GUARDRAILS.md` SIGN 1, `create-plan.md` §5c): when `plan_to_exec_gate == human`, do NOT auto-continue to execution — the user decides when to start. When `plan_to_exec_gate == reviewer-auto`, auto-continue to execution once `approved` is reached.

---

## Cost Reference

One measured run, kept as an order-of-magnitude anchor rather than a price list. Read the
rows as "a planner tier costs tens of dollars and a review round costs single digits" —
the ratio is the durable part; the absolute numbers move with every price change.

| Configuration | Empirical Cost | Turns | Notes |
|---------------|---------------|-------|-------|
| `architecture_single_shot` @ high, 2 MEUs (D1+D7) | $26.67 | 26 | Hit $25 cap before R2 |
| Codex R1 @ high (first review) | ~$2-4 | — | Subscription |
| Codex R2-R3 @ medium (follow-up) | ~$0.80-1.50 | — | Subscription |
| **Total (planner + 3 Codex rounds)** | **~30 to 35 USD** | | |

---

## Comparison with Standard `/create-plan`

| Aspect | Standard `/create-plan` | Delegated Plan Creation |
|--------|------------------------|------------------------|
| Planner | Current agent (`coordinator` class) | Claude CLI (`architecture_single_shot` / `coordinator`) |
| Review dispatch | Planner dispatches Codex | **Orchestrator** dispatches Codex |
| Corrections | Planner applies + re-dispatches | **Orchestrator** applies + re-dispatches |
| Context cost | Uses orchestrator context window | Preserves orchestrator context |
| Total cost | Lower (single agent) | Higher (planner + orchestrator + reviewer) |
| Best for | Standard plans | Complex plans, context preservation, model-quality experiments |

---

## Hard Rules

1. **The planner NEVER dispatches Codex.** This avoids 3-level subprocess chains and saves planner budget.
2. **The orchestrator applies all corrections.** Corrections are mechanical (file edits) and don't need `architecture_single_shot`/`coordinator` reasoning.
3. **Codex R1 uses `high` effort; R2+ uses `medium`.** First review is substantive; follow-ups verify mechanical fixes.
4. **Budget the planner generously** — size the cap from the class's catalog band. Under-budgeting causes the planner to stop mid-plan.
5. **Always use stdin pipe** for the planning prompt (`Get-Content prompt.txt | claude -p ...`).
6. **Check CLI versions before first dispatch** in the session.
