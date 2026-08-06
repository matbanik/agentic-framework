---
description: Plan and execute corrections for plan-document review findings. Fixes plan files, task contracts, and workflow docs — never production code.
---

# Plan Corrections Workflow

Use this workflow when a `/plan-critical-review` has produced findings and you want to resolve them. This workflow corrects **plan documents, task contracts, and workflow docs** — it never touches production code, tests, or implementation files.

This is the workflow for prompts like:

- "Fix all findings from the plan review"
- "Apply corrections to the implementation plan"
- "Resolve the plan-critical-review findings"

// turbo-all
// NOTE: turbo-all sets SafeToAutoRun=true for non-destructive commands (rg, Get-Content, etc.).
// It does NOT override AGENTS.md §Commits: "Never auto-commit." Git commit/push still requires explicit user direction.

## Write Scope (Non-Negotiable)

This is a plan-correction workflow.

Allowed file writes:

- `docs/execution/plans/*/implementation-plan.md`
- `docs/execution/plans/*/task.md`
- `.agent/workflows/*.md`
- `.agent/docs/*.md`
- `.agent/context/*.md`
- `.agent/context/handoffs/*-plan-critical-review.md` (correction log appended)
- `AGENTS.md`
- `docs/execution/README.md`

Forbidden file writes:

- production code (`packages/`, `ui/`, `mcp-server/`)
- test files (`tests/`)
- `docs/build-plan/` sections that describe runtime behavior (unless the plan review explicitly cited them as incorrect)

If a finding requires production code changes, record it as a deferred item and route to `/execution-corrections`.

---

## Prerequisites

Read these files in order:

1. `AGENTS.md`
2. `.agent/context/current-focus.md`
3. `.agent/context/known-issues.md`

---

## Auto-Discovery (No User Input Required)

The agent discovers the review findings file automatically.

### Discovery Steps

```powershell
# Find the most recent plan-critical-review handoff
Get-ChildItem .agent/context/handoffs/*-plan-critical-review.md |
  Sort-Object LastWriteTime -Descending | Select-Object -First 1
```

### Resolution Logic

1. **Primary target**: the most recent `*-plan-critical-review.md` file
2. **Working context**: use the latest dated update inside that file as the current state
3. If the latest update verdict is `approved`, inform the user that no open findings remain
4. If the latest update verdict is `corrections_applied`, inform the user that corrections were already applied and a `/plan-critical-review` re-review is needed before further corrections
5. If the latest update verdict is `changes_required`, use that update's findings as the working set

### Scope Override

If the user provides an explicit review file path, use that instead of auto-discovery.

---

## Workflow Steps

### Step 1: Parse Findings (Orchestrator)

Read the auto-discovered review file and extract a structured findings list:

| # | Severity | Summary | File(s) | Line(s) |
|---|----------|---------|---------|---------|

For each finding, capture:
- Severity (Critical/High/Medium/Low)
- One-line summary
- Affected file(s) and line(s)
- Reviewer's suggested fix (if any)

---

### Step 2: Verify Each Finding (Tester)

For every finding, verify it against live file state:

1. **Read the exact line(s)** cited in the finding
2. **Confirm or refute** the issue still exists
3. **Check for related issues** the reviewer may have missed

Use `rg` and file reads — do not trust the review's line numbers blindly.

Output a verified findings table:

| # | Severity | Verified? | Current Line(s) | Notes |
|---|----------|-----------|-----------------|-------|

### Step 2b: Categorize and Generalize (Tester)

For each verified finding:

1. **Categorize it** — assign a category label (e.g., "task contract gap", "stale reference", "validation weakness", "source-basis missing", "orphan/baseless deferral — missing Out-of-Scope *Basis* or unscheduled MEU (C2/PR-7)")
2. **Search for siblings** — run `rg` for the same pattern across all similar files
3. **Document siblings** — add to the findings table

---

### Step 3: Create Corrections Plan (Orchestrator)

For each verified finding, specify the exact fix:

- **File**: absolute path
- **What to change**: before → after (diff or description)
- **Why**: link back to finding # and severity

Group fixes by file. Update the corrections plan **in the project folder** (`docs/execution/plans/{date}-{project-slug}/implementation-plan.md`) — the single source of truth. **Never** create a `RequestFeedback:true` mirror artifact (GUARDRAILS SIGN 3, Layer 1 — that path triggers the auto-approval injection on harnesses with `injects_auto_approval: yes`). Corrections applied inline by the orchestrator (doc-only, no code) are reversible and auto-proceed; they need no separate approval gate.

---

### Step 4: Execute Corrections (Coder)

Apply all fixes. Rules:

1. Read the exact lines before editing (get current line numbers)
2. Apply fixes bottom-to-top within each file to avoid line shifts
3. Multiple non-adjacent edits in the same file → single edit call
4. Single contiguous edit → single edit call

---

### Step 5: Verify Corrections (Tester)

Re-run the verification commands from Step 2 to confirm all findings are resolved.

Additionally run:

```powershell
# Cross-reference check for stale terms
rg -n "<old-slug-pattern>" .agent/workflows/ .agent/docs/ AGENTS.md docs/execution/

# Phrase variant check
rg -n -i "<old-phrase>|<old-phrase-slugified>" .agent/workflows/ .agent/docs/
```

### Step 5b: Cross-Doc Sweep

If any correction changed a contract or workflow reference:

```powershell
# Search for old pattern across all canonical docs
rg -n -i "<old-pattern>" .agent/ docs/ AGENTS.md
```

Update all references. Document: "Cross-doc sweep: N files checked, M updated."

### Step 5c: Correction Blast-Radius Census (Required Per Correction)

> **Why this step exists.** A correction is a change with its own blast radius. On a large plan,
> roughly a quarter of historical review rounds existed *only* to catch a defect introduced by the
> previous round's fix — the reviewer's next pass was silently serving as the corrector's
> missing regression check, at a cost of one full round per regression. Step 5b sweeps for the
> *old pattern* across docs; this step sweeps for every *other statement of the value you just
> changed*, inside the plan itself.

For every literal, term, count, set, threshold, or predicate that a correction changed, `rg`
**both** plan files (`implementation-plan.md` and `task.md`) for every other site that states
that value, and record each hit in the correction log marked `updated` or `confirmed-consistent`:

```powershell
# One census per changed value, unfiltered to a P0 receipt. -F = literal text, so regex
# metacharacters inside the value cannot silently change what you searched for.
$plan = "docs/execution/plans/<project>/implementation-plan.md"
$task = "docs/execution/plans/<project>/task.md"

rtk proxy rg -F -n "<old-value>" $plan $task *> {{RECEIPTS_DIR}}/census-<slug>-old.txt
$rc = $LASTEXITCODE   # capture IMMEDIATELY (P0), before Get-Content or anything else
if ($rc -gt 1) { Get-Content {{RECEIPTS_DIR}}/census-<slug>-old.txt; exit $rc }

rtk proxy rg -F -n "<new-value>" $plan $task *> {{RECEIPTS_DIR}}/census-<slug>-new.txt
$rc = $LASTEXITCODE
if ($rc -gt 1) { Get-Content {{RECEIPTS_DIR}}/census-<slug>-new.txt; exit $rc }
```

> `rg` exit codes: `0` = matched, `1` = no match, `>1` = a real execution/IO error. Only `>1`
> is a failure. Do **not** treat `1` as an error — for the *old* value it is the good outcome
> (nothing stale left), and for the *new* value it means your edit did not land where you
> thought. Never let a silent `0` from an unchecked pipeline stand in for either.

Rules:

1. **A truncated grep is not a census.** Never `head`/`Select-Object -First` a census sweep —
   the whole point is the hit you did not expect. Read the receipt in full.
2. **Both directions.** Sweep the *old* value (to find sites you missed) and the *new* value
   (to confirm every site now agrees).
3. **Declare the semantic variants — a fixed-string sweep cannot find them for you.** The same
   rule spelled as prose, as a set literal, and as a SQL predicate is three sites, and no
   search for one form finds the other two. Before sweeping, write down every phrasing the
   value plausibly takes in this plan, and sweep each. A value that turns out to be stated at
   many sites is itself a finding: promote it to a named definition per the single-statement
   rule (`create-plan.md` Step 4) rather than editing N places again next round.
4. **Gate on the census.** A correction submitted without its census receipt is incomplete and
   may not be re-dispatched. This is self-enforced here and independently checked by the
   reviewer on round 2+ (`plan-critical-review.md` PR-6) — the corrector is not the only
   party looking.

Document: "Blast-radius census: K values changed, V variants swept, N sites found, M updated, N-M confirmed consistent."

---

### Step 6: Write Handoff (Documenter — NOT Reviewer)

> [!CAUTION]
> **Self-Approval Prohibition.** The corrections agent is the implementer (coder role). It MUST NOT set the verdict to `approved`. Only a subsequent `/plan-critical-review` pass — run by the reviewer role — may set `approved`. The corrections agent sets `corrections_applied` to signal readiness for re-review.

Update the same canonical plan-critical-review handoff in `.agent/context/handoffs/`:

- append a dated `Corrections Applied` section
- include plan summary, changes made, and verification results
- set verdict to `corrections_applied` (never `approved` — that requires an independent reviewer pass)
- keep the full review thread in that single file
- update frontmatter `verdict:` field to `corrections_applied`

---

### Step 7: Completion Timestamp (Mandatory Exit Gate)

> [!IMPORTANT]
> **Context-rot guard.** Re-read this workflow file before proceeding.
> If you are resuming after context truncation, this step will not exist in your context unless you re-read.

The **very last line** of the agent's chat response must be the timestamp skill output, copied verbatim.

This is a hard exit requirement for every `/plan-corrections` response, including short correction summaries.

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

Compressed variant for correction summaries:

```text
Corrections applied to <canonical-review-path>. Status: corrections_applied. Key evidence: <one sentence>.
🕐 Completed: YYYY-MM-DD HH:MM (TZ)
```

The compressed variant still requires invoking the timestamp skill and copying its real output verbatim for the last line.

---

## Hard Rules

1. **Always verify findings before fixing.** Reviews can have stale line numbers.
2. **Never skip a finding without explanation.** If refuted, say why.
3. **Group multi-file edits by file.** Minimize tool calls.
4. **Verification must be slug/anchor-aware.** Check both space form and slug form.
5. **User approval required before execution.** Plan → approve → execute → verify.
6. **Resolve the canonical review first.** Work from `*-plan-critical-review.md` and update that same file.
7. **Fix general, not specific.** Search for ALL instances of the same category across similar files.
8. **Never touch production code.** If a finding requires code changes, defer to `/execution-corrections`.
9. **Never self-approve.** The corrections agent MUST NOT set the review verdict to `approved`. Use `corrections_applied` to signal readiness for re-review. Only `/plan-critical-review` (reviewer role) may issue `approved`.

---

## Output Contract

Deliver to the user:

1. Auto-discovered review target
2. Verified findings count (confirmed vs refuted)
3. Corrections plan (for approval)
4. After execution: verification results + handoff path

---

## Orchestration Flow

This workflow is part of a four-workflow orchestration cycle:

1. `/create-plan` → plan new work
2. `/plan-critical-review` → review a new plan
3. `/plan-corrections` → resolve plan-review findings (this workflow)
4. `/execution-critical-review` → review completed implementation work

When to switch:

- Use `/plan-critical-review` first to **produce** the review findings.
- Use this workflow (`/plan-corrections`) to **resolve** plan-level findings.
- Use `/execution-corrections` for production code corrections.

## HARD STOP

> [!CAUTION]
> **Do NOT autonomously chain into `/plan-critical-review`, `/execution-corrections`, or any other workflow after completing corrections.** You MUST stop here and report the canonical review handoff path to the user. The user decides what happens next.

**Workflow complete.** Report the handoff path and wait for user direction.
