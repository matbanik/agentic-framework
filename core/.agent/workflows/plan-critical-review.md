---
description: Plan-review-only critical review workflow. Reviews unstarted execution plans for accuracy, consistency, and readiness before implementation begins.
---

# Plan Critical Review Workflow

Use this workflow to adversarially review an **unstarted execution plan** before implementation begins. This workflow produces findings only — it never fixes issues or reviews completed implementation work.

This is the workflow for prompts like:

- "Review the newest plan before implementation starts"
- "Check the implementation plan for consistency"
- "Verify the task contract is correct"

// turbo-all
// NOTE: turbo-all sets SafeToAutoRun=true for non-destructive commands (rg, Get-Content, etc.).
// It does NOT override AGENTS.md §Commits: "Never auto-commit." Git commit/push still requires explicit user direction.

## Write Scope (Non-Negotiable)

This is a review-only workflow.

Allowed file writes:

- `.agent/context/handoffs/{plan-folder-name}-plan-critical-review.md`

Forbidden file writes:

- all product code (`packages/`, `ui/`, `mcp-server/`)
- tests
- docs outside the canonical review handoff
- plan files
- existing work handoffs under review

If a finding suggests a fix, record it in the canonical review handoff and stop. Do not patch the repo. Use `/plan-corrections` for fixes.

---

## Role Sequence

1. `orchestrator` (scope + auto-discovery)
2. `tester` (evidence/verification commands for docs, links, grep sweeps)
3. `reviewer` (severity-ranked findings and verdict)

> `researcher` is optional only when external fact-checking is required.
> `guardrail` is usually not required for docs-only review.
> **No coder role.** This workflow produces findings only — never fixes. Use `/plan-corrections` to resolve findings.

---

## Auto-Discovery (No User Input Required)

The agent discovers the review target automatically. The user only needs to invoke the workflow — no file paths required.

### Discovery Steps

```powershell
# 1. Find recent execution plan folders
Get-ChildItem docs/execution/plans/ -Directory |
  Sort-Object LastWriteTime -Descending | Select-Object -First 5

# 2. Inspect the newest candidate plan's task state
Get-Content docs/execution/plans/<candidate>/task.md

# 3. Confirm the plan is genuinely unstarted
# - implementation tasks are still `pending` / unchecked
# - no MEU handoff paths created by the plan exist yet
# - no task items indicate completed coding, testing, or handoff creation
```

### Mode Confirmation

Choose this workflow (plan review) when all of the following are true:

1. No correlated work handoff exists yet for that plan
2. `task.md` shows implementation has not started yet
3. The user did not explicitly request review of a completed handoff

If implementation handoffs already exist for the plan, use `/execution-critical-review` instead.

### Scope Override

If the user provides explicit paths, use those instead of auto-discovery.

If the user provides an execution plan path with no `only` constraint, review the full plan folder (`implementation-plan.md` + `task.md`) even if no handoff exists yet.

### Canonical Review File Rule

Derive the review handoff path from the correlated execution plan folder:

- `.agent/context/handoffs/{plan-folder-name}-plan-critical-review.md`

Example: `docs/execution/plans/2026-03-07-commands-events-analytics/` → `.agent/context/handoffs/2026-03-07-commands-events-analytics-plan-critical-review.md`

If the canonical review file already exists, append a new dated section to it instead of creating another handoff file.

---

## Plan Creation Contract (Required)

When creating a plan for this workflow, every task must include:

- `task`
- `owner_role`
- `deliverable`
- `validation` (exact command(s))
- `status`

### Canonical Plan Template

| task | owner_role | deliverable | validation | status |
|---|---|---|---|---|
| Auto-discover review targets | `orchestrator` | Review mode + target plan folder | `Get-ChildItem` commands above + `Get-Content <task.md>` | `pending` |
| Load context and target artifact | `orchestrator` | Scoped review objective + target list | `Get-Content <target>` | `pending` |
| Run evidence sweeps | `tester` | Command outputs (grep/diff/link checks) | `rg`, `git diff`, file reads | `pending` |
| Produce findings-first review | `reviewer` | Severity-ranked findings + verdict | Cross-check line references | `pending` |
| Write or update canonical review handoff | `reviewer` | Canonical review file for the correlated plan folder | file created or updated + readable | `pending` |

---

## Workflow Steps

## Step 1: Discover and Scope the Review (Orchestrator)

Run the auto-discovery commands to verify this is an unstarted plan. Define:

- **Objective**: what the review is checking (contract completeness, validation quality, source traceability, etc.)
- **Out-of-scope**: what to exclude
- **Required scope**: `implementation-plan.md`, `task.md`, and any canonical docs/specs those files cite as authority
- **Additional scope**: registry, prior approved reflections/handoffs, or build-plan docs if the plan depends on them for carry-forward rules

---

## Step 2: Load Context and Evidence (Orchestrator + Tester)

Read:

1. Primary target: the unstarted execution plan folder
2. `implementation-plan.md` and `task.md`
3. Relevant related files likely to drift (indexes, references, downstream links, registry, prior canon)
4. Canonical docs cited as authority by the plan

---

## Step 3: Run Critical Verification Sweeps (Tester)

Use fast, reproducible command checks. Prefer `rg`.

### Required Sweep Types (Plan Review Mode)

1. **Plan-task consistency** — Do `implementation-plan.md` and `task.md` describe the same project scope, task order, and outputs?
2. **Status readiness** — Does file state really indicate not-started work, or has implementation already begun?
3. **Role/ownership consistency** — Does every task include the required role, deliverable, validation command, and status?
4. **Validation specificity** — Are validation commands exact, runnable, and scoped to the work described?
5. **Dependency/order correctness** — Are MEUs sequenced coherently, with no impossible order or missing prerequisites?
6. **Source-traceability** — Are acceptance criteria and non-spec rules tagged to `Spec`, `Local Canon`, `Research-backed`, or `Human-approved` sources?
7. **Scope-discipline (control C2)** — Is every row in the plan's **Out of Scope** table evidence-backed, not self-asserted? `deferred` rows must name a MEU-ID that actually exists in `meu-status.yaml` / the grouping; `out-of-scope` rows must cite a real source in *Basis* (build-plan line ref / ADR / `Human-approved`). The high-risk failure is contract work mislabeled `out-of-scope` to dodge the MEU-ID requirement — verify the cited build-plan lines genuinely omit the item.
8. **Referenced-artifact existence** — extract every file path the plan's `validation` cells and prose gates invoke (scripts, tools, configs, fixtures, generated clients, schemas — not only `tools/*.py`) and `Test-Path` each one. **Existence before semantics:** do not review the argument shape, flags, or assertions of a command whose executable does not exist and is not scheduled to be written — say so and stop reviewing that surface. (A plan review once spent eight rounds refining assertions for a `tools/` script that was never on disk; one `Test-Path` in round one would have closed it.) **Severity follows the Materiality Gate, not the absence itself:** a path absent from disk *and* from the plan's Files-Created inventory, which a task row nonetheless depends on to prove its deliverable, is `High` — the gate would false-pass a materially missing executable. A path that is merely misspelled, moved, or missing from the inventory while the plan plainly intends to create it is clerical (`Low`) — name the correct path and move on.
9. **Repeated-literal sweep** — `rg` the plan and task files for state sets, thresholds, enumerations, and predicates that are spelled out at two or more sites (`{active, indeterminate}`, row caps, status lists, error-code sets). Each cluster restated in more than one place is **one** finding naming the site that should hold the canonical definition — not one finding per site. A literal restated at N sites is a stale clause scheduled for the next correction round.

### Suggested Commands (Adapt Per Task)

```powershell
# 1) Read the primary review artifact and target files
Get-Content <primary-artifact>
Get-Content docs/execution/plans/<project>/implementation-plan.md

# 2) Check cross-references
rg -n "<old-term>" .agent/workflows/ .agent/docs/ AGENTS.md

# 3) Inspect actual diffs for claimed files
git diff -- <files>

# 4) Verify validation commands are runnable
# Manually inspect each task row's validation column

# 5) Scope-discipline (C2): pull the Out of Scope table, then confirm every row's basis
rg -n -A 20 "## Out of Scope" docs/execution/plans/<project>/implementation-plan.md
#   - for each `deferred` row: confirm its MEU-ID appears here ↓ (no match ⇒ unscheduled ⇒ finding)
rg -n "<MEU-ID>" .agent/context/meu-status.yaml .agent/context/grouping/
#   - for each `out-of-scope` row: open the cited build-plan lines and confirm they truly omit the item

# 6) Sweep 8 — referenced-artifact existence.
#    Capture the UNFILTERED receipt first (P0 exact-evidence), then extract + dedupe from it.
#    `rg -o` still prefixes `file:line:`, so piping it straight into Sort-Object -Unique does
#    NOT deduplicate paths — dedupe the extracted path field, not the whole record.
$rx = "(tools|scripts)/[A-Za-z0-9_./-]+\.[A-Za-z0-9]+"
rtk proxy rg -o $rx docs/execution/plans/<project>/ *> {{RECEIPTS_DIR}}/sweep8-paths.txt
$rc = $LASTEXITCODE   # capture IMMEDIATELY (P0). rg: 0 = matched, 1 = no match, >1 = real error
if ($rc -gt 1) { Get-Content {{RECEIPTS_DIR}}/sweep8-paths.txt; exit $rc }
#    Re-match the regex per line instead of splitting on ':' — a receipt also carries RTK
#    banners and diagnostics, and splitting those on ':' invents paths that were never cited.
$paths = Get-Content {{RECEIPTS_DIR}}/sweep8-paths.txt |
  ForEach-Object { [regex]::Matches($_, $rx) } | ForEach-Object { $_.Value } | Sort-Object -Unique
#    Widen the pattern per plan: config/fixture/schema/generated-client paths are in scope too.
#    Expect false positives where the prefix matches mid-path (e.g. `tui/tools/generate.go`
#    reported as `tools/generate.go`); resolve each `False` against the Files-Created inventory
#    and the real repo layout before writing a finding.
$paths | ForEach-Object { [pscustomobject]@{ path = $_; exists = (Test-Path $_) } }
#    - for each `exists = False`: confirm whether it appears in the plan's Files-Created inventory

# 7) Sweep 9 — repeated-literal census (never head-truncate a census; -F for literal text)
rtk proxy rg -F -n "<state-set-or-threshold-literal>" docs/execution/plans/<project>/ *> {{RECEIPTS_DIR}}/sweep9-census.txt
$rc = $LASTEXITCODE; if ($rc -gt 1) { Get-Content {{RECEIPTS_DIR}}/sweep9-census.txt; exit $rc }
#    rc 1 = zero hits, which for a census is a RESULT (nothing restated), not a failure.
```

---

## Step 4: Adversarial Review (Reviewer)

Use the reviewer role output contract and report **findings first**.

> **Reviewer effort (D4, 2026-06-13):** `medium` for routine plan review; `high` for plans touching risk paths / contract surfaces / security; `max`/`xhigh` only for tagged verifiable deep sub-reviews. Report every finding with confidence + severity and let a downstream step filter — do not self-suppress low-confidence items, but assign final severity through the Materiality Gate below. See `.agent/skills/cli-dispatch/SKILL.md` §Reviewer Effort Policy.

### Intent Anchor (Required First Output)

Before generating any finding, write 1–2 sentences stating what executing this plan is
supposed to deliver for the user. The verdict must answer **"would executing this plan
deliver that objective?"** first. Every blocking finding must name the checklist item,
template requirement, or source rule it violates — a finding that cannot cite its violated
contract is an observation, not a blocker.

### Materiality Gate (Required — Applied Before Assigning Final Severity)

1. **Clerical findings are `Low` and never block.** Typos, count/label transpositions,
   row-numbering or cross-reference drift, Markdown table syntax, stale numbers in prose,
   and template-compliance gaps are clerical whenever an intelligent reader can trivially
   infer the correct value. State the correction in one line inside the finding and move
   on. Clerical findings may not be rated `Medium`/`High` and may not contribute to
   `changes_required`.
2. **Out-of-contract observations never block.** A requirement you believe *should* exist
   but that no build-plan section, spec, or checklist item states goes into a short
   `Out-of-Contract Observations` list (≤ 5 items, one line each) — never into the
   Findings table as a blocker. Do not invent scope for the plan.
3. **Cap meta-validation of the plan's own predicates.** The plan's `validation` cells and
   closeout-check commands are reviewed for one property only: would they false-pass a
   *materially missing deliverable*? A predicate defect is blocking only when you
   demonstrate that concrete false-pass. Predicate-shape completeness (row counts,
   template literals, regex variants, delimiter lists) is clerical. Do not spend later
   rounds demanding deeper mutations of predicates already fixed — record residual risk
   once and stop.
4. **No nearby-mutation escalation.** Once a finding on a surface is fixed, a later-round
   finding on that same surface must demonstrate a NEW, materially different failure of
   the plan's ability to deliver — not a deeper variant of the same class.

### Plan Review Checklist (Required)

| # | Check | What To Look For |
|---|---|---|
| PR-1 | Plan/task alignment | `implementation-plan.md` and `task.md` describe the same scope and order |
| PR-2 | Not-started confirmation | No file-state evidence that coding/testing/handoffs already began |
| PR-3 | Task contract completeness | Every task has `task`, `owner_role`, `deliverable`, `validation`, `status` |
| PR-4 | Validation realism | Commands are specific enough to prove the intended work |
| PR-5 | Source-backed planning | Rules beyond explicit spec text are tagged to an allowed source basis |
| PR-6 | Handoff/corrections readiness | Multi-MEU handoff paths are explicit when applicable, and review findings can be resolved via `/plan-corrections`. **On round 2+, also verify the corrector's blast-radius census** (`plan-corrections.md` Step 5c): the resubmission names a census receipt, the receipt is untruncated, and each hit carries a per-hit disposition (`updated` / `confirmed-consistent`) — a bare count is not a disposition. The two live in different places and both must be present: the **receipt** is the raw unfiltered sweep output and must inventory every hit, while the **correction log** assigns each `file:line` in it a disposition. A receipt with no log is an uninterpreted sweep; a log with no receipt is an unverifiable claim. A resubmission whose census is missing, truncated, or undispositioned is a **pre-verdict procedural gate**, not a severity-rated finding: return `changes_required` naming only that, and do not review the corrected content this round (see Verdict Rule). Rating it `Medium` would let the Verdict Rule approve straight past it — a false-passing gate of exactly the kind PR-8 exists to catch. |
| PR-7 | Scope-discipline (control C2) | Every **Out of Scope** row is evidence-backed: `deferred` → a MEU-ID present in `meu-status.yaml`; `out-of-scope` → a real source in *Basis* whose cited build-plan lines truly omit the item. Flag any blank/hand-waved *Basis*, any unscheduled MEU target ("future MEU", "a wiring session"), and any contract work relabeled `out-of-scope` to escape the MEU-ID gate. An unjustified deferral is a SKIP → `changes_required`. **Substance vs. labeling:** the blocking rating is for genuinely missing/disguised work; a substantively evidenced deferral with a wrong label or reference is clerical (`Low`) — name the correct reference and move on. |
| PR-8 | Control reachability & totality | Every control the plan asserts is bound to reality on three axes: an **observable** it is measured on, a **traceable call chain** from a named production entrypoint to the code that produces that observable, and a **negative oracle** that asserts on the observable under an adversary condition the positive contract cannot satisfy. Rate `High` only where vacuity is *demonstrated* — you can name the missing producer, or trace the chain to a dead end (a counter no path writes, a gate invoked by no pipeline, a resolver reachable only from tests). An otherwise-evident caller the plan merely failed to spell out is clerical (`Low`); naming an unreached wrapper as the "production caller" is not a chain. Also check that classifications over states/exceptions/outcomes are exhaustive in the right sense — closed-world enums exhaustive at compile time, open-world inputs **fail closed** on the unrecognized case — and that every read-then-write pair names its actual atomicity mechanism (transaction, lock, CAS, or a single atomic statement — do not demand a transaction where a CAS is correct). |
| PR-9 | Single-statement discipline | Sets, thresholds, enumerations, and predicates referenced by more than one AC or task row are defined **once** under a name and referenced by name elsewhere (see Sweep 9). Report each restated cluster once, not once per site. `Low` by default, including where one spelling is trivially inferable as the stale one — say which is canonical and move on. `High` only where two live spellings imply **materially different behavior** and the plan gives no way to tell which governs: that is an ambiguous contract, not a typo. |

### Docs Review Checklist (Required)

| # | Check | What To Look For |
|---|---|---|
| DR-1 | Claim-to-state match | Handoff says a change happened and file state proves it |
| DR-2 | Residual old terms | Old phrase/slug variants still present (`foo bar` and `foo-bar`) |
| DR-3 | Downstream references updated | Indexes, cross-links, and anchors updated after rename/move |
| DR-4 | Verification robustness | Handoff checks would actually catch regressions introduced by the change |
| DR-5 | Evidence auditability | Commands/diffs are reproducible (not placeholders only) |
| DR-6 | Cross-reference integrity | Architectural changes are consistent across all canonical docs |
| DR-7 | Evidence freshness | Handoff-claimed counts match reproduced command output |
| DR-8 | Completion vs residual risk | If residual risk acknowledges known gaps, conclusion must NOT say "implementation complete" |

### Severity Guidance

- `Critical`: Dangerous instructions/security regressions or decisions documented incorrectly
- `High`: Incorrect contracts, false implementation claims, or plan that materially misstates scope
- `Medium`: Portability, maintainability, verification-quality, or navigation issues
- `Low`: Auditability, wording, minor evidence quality gaps, all clerical findings (Materiality Gate #1)

### Verdict Rule (Blocking Threshold)

`changes_required` requires at least one evidence-backed `High`/`Critical` finding that the
plan would fail to deliver its objective, materially misstates scope, sequences work
impossibly, omits a required deliverable, or contains a demonstrated false-passing gate.

**One procedural exception, evaluated before severity:** on a round-2+ resubmission whose
blast-radius census is missing, truncated, or undispositioned (PR-6), return
`changes_required` naming that alone. The evidence needed to judge the corrections is absent,
so there is nothing to rate — this is a precondition failure, not a severity judgment, and it
is the only path to `changes_required` that does not require a `High`/`Critical` finding.
Clerical, formatting, template, or predicate-shape findings alone — at any count — produce
`approved` with correction notes, not `changes_required`.

When approving with correction notes, record the surviving clerical/observation items in
the verdict `summary` (and the review handoff prose), NOT in the structured `findings`
array — the verdict schema requires an empty findings array for `approved`. Never choose
`changes_required` merely to have a place to list non-blocking notes.

---

## Step 5: Write or Update the Canonical Review Handoff (Required Exit Gate)

Write to: `.agent/context/handoffs/{plan-folder-name}-plan-critical-review.md`

If that file already exists, append a new dated review update section.

The workflow is incomplete until the canonical review handoff exists and is readable.

> **Start from** [`.agent/context/handoffs/REVIEW-TEMPLATE.md`](file:///{{PROJECT_ROOT}}/.agent/context/handoffs/REVIEW-TEMPLATE.md) (v2.1)
>
> **Verbosity control**: Set `requested_verbosity` in the review YAML frontmatter. See `.agent/docs/context-compression.md §Verbosity Tiers`.

Fill the template sections:
- `Findings` table with severity-ranked findings and file:line references
- `Checklist Results` with PR/DR check outcomes
- `Verdict` with explicit `approved` or `changes_required`

### Required Review Handoff Content

1. Scope reviewed (including auto-discovered targets)
2. Commands executed
3. Findings with file/line references
4. Explicit verdict (`approved` or `changes_required`)
5. Concrete follow-up actions
6. If this is not the first pass, a dated update heading

---

## Pre-Edit Guard

Before any file edit:

1. derive the canonical review handoff path for plan review mode
2. verify the intended edit target exactly matches that canonical handoff path

If the target path is anything else, abort the edit and continue in findings-only mode.

---

## Step 6: Save Session Memory (Optional but Recommended)


- what was reviewed
- key findings
- whether fixes should be applied via `/plan-corrections`

---

## Step 7: Completion Timestamp (Mandatory Exit Gate)

> [!IMPORTANT]
> **Context-rot guard.** Re-read this workflow file before proceeding.
> If you are resuming after context truncation, this step will not exist in your context unless you re-read.

The **very last line** of the agent's chat response must be the timestamp skill output, copied verbatim.

This is a hard exit requirement for every `/plan-critical-review` response, including short rechecks.

Required sequence:

1. Re-read this workflow file to confirm all prior steps are complete.
2. Invoke the timestamp skill by reading `.agent/skills/timestamp/SKILL.md`.
3. Run the stamp script with the Windows redirect-to-file pattern:

```powershell
# // turbo
python .agent/skills/timestamp/scripts/stamp.py *> {{RECEIPTS_DIR}}/stamp.txt
```

4. Read `{{RECEIPTS_DIR}}/stamp.txt` with the file viewer.
5. Copy the file's single output line verbatim as the final chat line.

No text, bullets, caveats, or sign-off may appear after the timestamp line.

Compressed variant for rechecks:

```text
Recheck appended to <canonical-review-path>. Verdict: <approved|changes_required>. Key evidence: <one sentence>.
🕐 Completed: YYYY-MM-DD HH:MM (TZ)
```

The compressed variant still requires invoking the timestamp skill and copying its real output verbatim for the last line.

---

## Hard Rules

1. **Never fix issues during this workflow.** This workflow produces findings only. Use `/plan-corrections` to resolve findings.
2. **Do not approve based on phrase-only grep checks** when heading renames or link anchors are involved.
3. **Do not treat the handoff as source of truth**; treat file state + diffs as source of truth.
4. **Do not bury findings behind summaries**; findings come first.
5. **Never review a review.** Auto-discovery excludes `*critical-review*`, `*-corrections*`, and `*-recheck*` handoffs as review seeds.
6. **If no implementation handoff exists yet, review the newest unstarted execution plan.** This is a plan-accuracy and consistency review.
7. **When plan-review findings require changes, route the fix phase through `/plan-corrections`.**
8. **One rolling review file per target.** Keep plan-review updates in the same `-plan-critical-review.md` file.
9. **Do not return a final response until the canonical review handoff has been created or updated successfully.**
10. **Do not modify any file unless the Pre-Edit Guard resolves to the canonical review handoff path.**
11. **Never block on clerical findings.** Apply the Materiality Gate: `changes_required` requires at least one evidence-backed `High`/`Critical` delivery-level finding (see Verdict Rule).
12. **Hold the plan's objective as the review target.** The question is "would executing this plan deliver its objective?", not "is every artifact formality satisfied?" — and never escalate a fixed surface with a deeper variant of the same class.

---

## Done Checklist

- [ ] No product files were modified
- [ ] Canonical review handoff was created or updated
- [ ] Review mode was correctly identified as `plan`
- [ ] Verdict is explicit (`approved` or `changes_required`)
- [ ] Final user response includes the canonical review handoff path

---

## Output Contract

Return to the user:

- Auto-discovered targets (what was reviewed)
- Findings (severity-ranked, file/line references)
- Open questions / assumptions
- Review verdict (`changes_required` or `approved`)
- Residual risk statement
- Path to the created or updated canonical review handoff

---

## Orchestration Flow

This workflow is part of a four-workflow orchestration cycle:

1. `/create-plan` → plan new work
2. `/plan-critical-review` → review a new plan before implementation (this workflow)
3. `/plan-corrections` → resolve plan-review findings
4. `/execution-critical-review` → review completed implementation work

When to switch:

- Use this workflow immediately after `/create-plan` when a new plan needs adversarial review.
- Use `/plan-corrections` if the verdict is `changes_required` and the user wants fixes applied.
- Use `/execution-critical-review` for reviewing implementation handoffs (not plans).

## HARD STOP

> [!CAUTION]
> **Do NOT autonomously chain into `/plan-corrections` or any other workflow after completing this review.** You MUST stop here and report the canonical review handoff path to the user. The user decides what happens next.

**Workflow complete.** Report the handoff path and wait for user direction.
