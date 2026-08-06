---
name: Completion Pre-Flight
description: Mandatory pre-flight checklist before any stop, report, or summary to the user during execution. Prevents premature stop by enforcing a deterministic re-read of the project task.md.
---

# Completion Pre-Flight

Executable checks follow `.agent/docs/output-evidence-policy.md`; defer to that file
for exact-evidence bypass and PowerShell 7 routing decisions.

**Trigger:** MUST be invoked before any stop, summary, or "implementation complete" report to the user during EXECUTION or VERIFICATION mode.

**Objective:** Prevent premature stop by ensuring all task.md items are complete before yielding control to the user. This is the procedural enforcement of the anti-premature-stop rule in AGENTS.md §Execution Contract.

> Tool names below (`view_file`, etc.) are capability placeholders, not literal tool names — see `.agent/docs/harness-profiles.md` for the substitution table (`read_tool`, `shell_tool`, `end_turn_signal`) and use your harness's actual read tool.

> This skill was created after root cause analysis of a premature stop incident where context truncation caused 16 unchecked task items to be silently dropped. See `premature_stop_analysis.md` in conversation `9986e441` for full RCA.

## Pre-Flight Checklist

Satisfy ALL before any stop/report event:

- [ ] **Canonical task.md read**: read (your harness `read_tool`) the project task.md at `docs/execution/plans/{project-slug}/task.md` — NOT the agent workspace copy
- [ ] **Unchecked count**: count `[ ]` items in the task table. If any remain that are not `[B]` blocked → **do NOT stop** — continue execution
- [ ] **Source of truth check**: confirm you updated the PROJECT task.md, not only the agent workspace copy
- [ ] **Post-MEU deliverables**: verify all post-MEU rows (registry, BUILD_PLAN, handoffs, reflection) are addressed or explicitly deferred as `[B]`
- [ ] **Artifact structural compliance**: verify every canonical handoff enumerated by
  the plan/task. Product paths use `{date}-{project-slug}-{MEU-ID}-handoff.md`;
  non-product `meus: []` paths use one project handoff at
  `{date}-{project-slug}-handoff.md`. The project review remains the rolling
  `{plan-folder-name}-implementation-critical-review.md` file.

> These items are the single source of truth — they enforce AGENTS.md §Execution Contract anti-premature-stop rule.

## SOP: Standard Operating Procedure

Follow this 4-step sequence before every stop/report:

### Step 1 — Read Canonical Task File

**FIRST ACTION — non-negotiable.** Before any reasoning about whether you are "done", execute this read call with your harness's `read_tool`. If ANY `[ ]` rows remain, you are NOT done — STOP reasoning about completion and resume execution immediately.

```
read: docs/execution/plans/{project-slug}/task.md
```

This re-injects the full task table into context, overriding any narrowed scope from checkpoint summaries.

### Step 2 — Count Remaining Work

Scan every row in the task table. Count:
- `[ ]` = not started (must be completed before stop)
- `[/]` = in progress (must be completed or checkpointed)
- `[B]` = blocked — evidence-gated (acceptable to leave ONLY with a linked follow-up AND, for external-error / missing-dependency cases, a pasted command + error file; subjective reasons like "too complex"/"no time" are invalid — see AGENTS.md §Execution Contract)
- `[x]` = complete

**Decision gate:**
- If `[ ]` count > 0 → **CONTINUE EXECUTION**, do not stop
- If `[ ]` count = 0 (only `[x]` and `[B]` remain) → proceed to Step 3

### Step 3 — Verify Source of Truth

Confirm that:
1. The PROJECT task.md (`docs/execution/plans/...`) has been updated with current status
2. The agent workspace task.md (if it exists) mirrors the project copy
3. No task was marked `[x]` only in the agent workspace copy

### Step 4 — Final Gate

Before composing the stop/summary message:
- [ ] All `[ ]` items resolved (completed or moved to `[B]`)
- [ ] Project task.md updated
- [ ] Evidence bundle references actual command output, not memory

Only after all gates pass → report to user.

## Structural Marker Checklist

When Step 6 (artifact structural compliance) fires, run these checks on each artifact created this session:

### Reflection files (`docs/execution/reflections/{date}-{slug}-reflection.md`)

Required markers — grep the file for each. **ALL must match or the reflection is non-compliant:**

```powershell
rtk proxy pwsh -NoProfile -Command { $path='<reflection-file>'; $patterns=@('Friction Log|Execution Trace','Pattern Extraction|Patterns to KEEP','Next Session Design Rules|RULE-','Efficiency Metrics','Rule Adherence','Instruction Coverage|schema: v1','sections:','loaded:','decisive_rules:'); foreach ($pattern in $patterns) { if (-not (Select-String -Path $path -Pattern $pattern -Quiet)) { Write-Error ('missing reflection pattern: '+$pattern); exit 1 } }; 'PASS: reflection markers' } *> {{RECEIPTS_DIR}}/reflection-structure.txt; $code=$LASTEXITCODE; Get-Content {{RECEIPTS_DIR}}/reflection-structure.txt; exit $code
```

> [!NOTE]
> Token counts, environment, and implementor-model fields are retired (2026-07-21) — do not emit or validate them.

> [!CAUTION]
> **Hard gate — not advisory.** If ANY marker above returns 0 matches, the reflection is structurally non-compliant. Execute: read (your harness `read_tool`) `docs/execution/reflections/TEMPLATE.md`, then rewrite the reflection using the full 7-section template structure. The YAML block alone is NOT a valid reflection — it is section 7 of 7.

> [!CAUTION]
> **If the exact reflection-marker receipt reports no `sections:` match, the Instruction Coverage YAML is missing.** This means Step 7.5 of `tdd-implementation.md` was skipped. Execute it now: read (your harness `read_tool`) `.agent/schemas/reflection.v1.yaml`, then emit the YAML block in the reflection file.

If ANY marker is missing → read (your harness `read_tool`) `docs/execution/reflections/TEMPLATE.md` and rewrite the reflection using the template structure.

### Handoff files

Run the checks for every path in the plan's Handoff Set: one
`.agent/context/handoffs/{date}-{project-slug}-{MEU-ID}-handoff.md` per product MEU,
or, when the plan is non-product (`meus: []`), one project handoff at
`.agent/context/handoffs/{date}-{project-slug}-handoff.md`.

Required markers:

```powershell
rtk proxy pwsh -NoProfile -Command { $path='<handoff-file>'; foreach ($pattern in @('Acceptance Criteria|AC-','CACHE BOUNDARY','Evidence|FAIL_TO_PASS','Changed Files')) { if (-not (Select-String -Path $path -Pattern $pattern -Quiet)) { Write-Error ('missing handoff pattern: '+$pattern); exit 1 } }; 'PASS: handoff markers' } *> {{RECEIPTS_DIR}}/handoff-structure.txt; $code=$LASTEXITCODE; Get-Content {{RECEIPTS_DIR}}/handoff-structure.txt; exit $code
```

If ANY marker is missing → read (your harness `read_tool`) `.agent/context/handoffs/TEMPLATE.md` and fix the handoff.

#### AC-table integrity gate (control C4 — HARD GATE)

The handoff AC table MUST cover **every** AC-ID declared in the plan's AC table. A silently dropped AC is the disclosure half of the "render-first, wire-later" skip class (e.g. an option-column or `Init`-fetch AC vanishing from the handoff). Verify:

```powershell
# Every AC-ID in the plan must appear in the handoff. Compare the two sets.
rtk proxy pwsh -NoProfile -Command { $planAcs=@(Select-String -Path docs/execution/plans/{slug}/implementation-plan.md -Pattern 'AC-[0-9]+(?:\.[0-9]+)?' -AllMatches).Matches.Value; $handoffAcs=@(Select-String -Path .agent/context/handoffs/{date}-{project-slug}-{MEU-ID}-handoff.md -Pattern 'AC-[0-9]+(?:\.[0-9]+)?' -AllMatches).Matches.Value; $missing=@(Compare-Object ($planAcs | Sort-Object -Unique) ($handoffAcs | Sort-Object -Unique) | Where-Object SideIndicator -eq '<='); if ($missing) { $missing; exit 1 }; 'PASS: complete AC set' } *> {{RECEIPTS_DIR}}/handoff-ac-check.txt; $code=$LASTEXITCODE; Get-Content {{RECEIPTS_DIR}}/handoff-ac-check.txt; exit $code
```

> [!CAUTION]
> If `Compare-Object` reports any plan AC missing from the handoff, the handoff is non-compliant. Either add the AC row (with its real status) or, if the work moved, add a Deferred Items row naming a **scheduled** MEU-ID (control C2). Do NOT close the session with an AC that exists in the plan but nowhere in the handoff.

### Review files (`.agent/context/handoffs/{date}-{slug}-*-critical-review.md`)

Required markers:

```powershell
rtk proxy pwsh -NoProfile -Command { $path='<review-file>'; foreach ($pattern in @('verdict:','findings_count:','Finding|Severity')) { if (-not (Select-String -Path $path -Pattern $pattern -Quiet)) { Write-Error ('missing review pattern: '+$pattern); exit 1 } }; 'PASS: review markers' } *> {{RECEIPTS_DIR}}/review-structure.txt; $code=$LASTEXITCODE; Get-Content {{RECEIPTS_DIR}}/review-structure.txt; exit $code
```

> **Fail-safe**: If you cannot find the artifact to grep (e.g., you haven't created it yet), that is itself a compliance failure — create the artifact from its template before proceeding.

## Closeout Artifact Quality Check

**Trigger:** Before marking ANY closeout task `[x]` (handoff, reflection, metrics).

**Root cause this addresses:** Context fatigue at session end causes agents to treat closeout artifacts as "checkbox items" — writing thin, template-violating content from stale memory instead of following the full template structure. This check is the enforcement mechanism.

### Pre-Write Verification

Before writing ANY closeout artifact, confirm:

- [ ] **Template loaded**: Did I read (via my harness `read_tool`) the relevant template (TEMPLATE.md) this session? If not, read it NOW.
- [ ] **Exemplar loaded**: Did I read (via my harness `read_tool`) a recent peer exemplar (most recent by date) for quality calibration? If not, read one NOW.
- [ ] **Not from memory**: Am I about to generate this artifact from the template I just read, or from a stale memory of what the template looks like? If the latter, re-read the template.

### Post-Write Verification

After writing each closeout artifact, verify:

- [ ] **Reflection quality gate**: File size > 2,000 bytes AND all 11 template sections have substantive answers (not `_Answer here_` or single-sentence responses for complex questions)
- [ ] **Handoff quality gate**: All 7 scored sections are populated with concrete evidence, not "pending" or "N/A" for blocking gates
- [ ] **Metrics row verified**: the exact metrics-tail receipt shows a row with today's date and all columns populated

### Anti-Patterns (Closeout-Specific)

> The following fenced block is an anti-pattern reference block and is not executable
> guidance.

```
# ❌ Writing reflection from memory
"I know the template has 11 sections..." → WRONG — read TEMPLATE.md first (your harness `read_tool`)

# ❌ Using Test-Path as the only quality check
Test-Path docs/execution/reflections/foo.md → only checks existence, NOT quality

# ❌ Treating closeout as "after the real work"
"Implementation is done, now just need to do the admin stuff" → WRONG mindset
```

## Post-Truncation Recovery Sequence

**When resuming after context truncation (checkpoint message):**

This is the highest-priority procedure after truncation. Execute it BEFORE addressing any specific issue mentioned in the checkpoint summary.

1. read (your harness `read_tool`) the project `task.md` at `docs/execution/plans/{project-slug}/task.md`
2. Count unchecked `[ ]` items — this is the remaining work queue
3. Read the current row's declared durable output; do not reload completed independent rows wholesale
4. Only then address the specific issue from the checkpoint summary
5. After resolving the immediate issue, continue the task table sequentially
6. Before stopping, re-execute this skill's full checklist (Steps 1–4 above)

> The checkpoint summary is a convenience aid, NOT a scope definition. The project task.md is the scope definition.

## Anti-Patterns (Never Do These)

> The following fenced block is an anti-pattern reference block and is not executable
> guidance.

```
# ❌ Update only the agent workspace task.md
write_to_file: C:\Users\Mat\.gemini\antigravity\brain\{id}\task.md  # WRONG source

# ❌ Treat "all tests green" as completion
"2299 passed, 0 failed → report to user"  # WRONG — tests green is a milestone, not a stopping point

# ❌ Jump to regression fix after truncation without reading task.md first
"Checkpoint says fix test_api_scheduling.py → do that → report done"  # WRONG — read task.md first

# ❌ Stop after fixing the immediate issue from checkpoint
"Fixed the regression → updated walkthrough → done"  # WRONG — check for remaining [ ] items
```

## When to Skip

This skill may be skipped ONLY for:
- **Human-directed stops**: User explicitly says "stop here" or "pause"
- **Context window checkpoint**: At 50% capacity, the checkpoint protocol in AGENTS.md applies instead (save state + notify human)

> [!CAUTION]
> **Dispatching the review is NOT a stop and is NOT a skip.** The orchestrator runs the review CLI, waits for the verdict file, and continues to H2 in the same turn (AGENTS.md §Execution Contract). Do not treat "I handed off to Codex" as the end of your turn — that is the premature-stop-before-H2 failure mode this skill exists to prevent.

All other stop events — especially after "tests pass", after fixing regressions, after context truncation, and after dispatching the review — MUST use this checklist.
