---
description: Execute corrections for implementation review findings. Fixes production code, tests, and infrastructure — never plan documents.
---

# Execution Corrections Workflow

Use this workflow when an `/execution-critical-review` has produced findings and you want to resolve them. This workflow corrects **production code, tests, and infrastructure** — it never touches plan documents, task contracts, or workflow files.

This is the workflow for prompts like:

- "Fix all findings from the implementation review"
- "Apply corrections to the code"
- "Resolve the execution-critical-review findings"

// turbo-all
// NOTE: turbo-all sets SafeToAutoRun=true for non-destructive commands (rg, Get-Content, etc.).
// It does NOT override AGENTS.md §Commits: "Never auto-commit." Git commit/push still requires explicit user direction.

## Write Scope (Non-Negotiable)

This is a production-code correction workflow.

Allowed file writes:

- `packages/**` (production code)
- `ui/**` (GUI code)
- `mcp-server/**` (MCP server code)
- `tests/**` (test files)
- `tools/**` (build/validation tooling)
- `.agent/context/handoffs/*-implementation-critical-review.md` (correction log appended)
- `.agent/context/meu-status.yaml` via SSOT CLI (if MEU state changes: `uv run python tools/meu_status.py update`)

Forbidden file writes:

- `docs/execution/plans/*/implementation-plan.md`
- `docs/execution/plans/*/task.md`
- `.agent/workflows/*.md`
- `AGENTS.md`
- `docs/build-plan/` (unless the review explicitly cited a runtime-behavior misstatement)

If a finding requires plan or workflow changes, record it as a deferred item and route to `/plan-corrections`. **IR-7/C2 deferral findings are the exception** — their default resolution is to implement the skipped work *here* (code+tests, in scope), not to route them away. See Step 2b.

---

## TDD Discipline (Mandatory)

> Tests FIRST, implementation after. Tests = specification.

When correcting findings that involve runtime behavior:

1. **Write or update tests first** that reproduce the finding as a failing test
2. **Confirm the test fails** (Red phase)
3. **Fix the production code** to make the test pass (Green phase)
4. **Never modify test assertions to make them pass** — fix the implementation instead

This applies to bug fixes too. See AGENTS.md §Testing & TDD Protocol.

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
# Find the most recent implementation-critical-review handoff
Get-ChildItem .agent/context/handoffs/*-implementation-critical-review.md |
  Sort-Object LastWriteTime -Descending | Select-Object -First 1
```

### Resolution Logic

1. **Primary target**: the most recent `*-implementation-critical-review.md` file
2. **Working context**: use the latest dated update inside that file as the current state
3. If the latest update verdict is `approved`, inform the user that no open findings remain
4. If the latest update verdict is `corrections_applied`, inform the user that corrections were already applied and a `/execution-critical-review` re-review is needed before further corrections
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

> **Context**: The "fix-specific-not-general" meta-pattern was the single biggest multiplier of review passes.

For each verified finding:

1. **Categorize it** — assign a category label (e.g., "error mapping gap", "stub inadequacy", "boundary validation gap", "weak test assertion")
2. **Search for siblings** — run `rg` for the same pattern across all similar files/routes/modules
3. **Document siblings** — add to the findings table
4. **Boundary validation gap** — search ALL sibling write paths for the same gap

> **IR-7 / C2 deferral findings (orphan or disguised `out-of-scope`) have a special resolution path — never re-defer them.** For each such finding, decide:
> - **Default: the work was wrongly skipped → implement it now.** Writing the missing code + tests is in scope for this workflow (TDD per Step 4). This is the correct resolution unless the deferral is genuinely legitimate.
> - **Only if the deferral is genuinely legitimate** (real dependency/sequencing reason): register the owning MEU via the SSOT CLI (`uv run python tools/meu_status.py update ...` — in scope), then route the plan's *Basis*/Out-of-Scope-table correction to `/plan-corrections` (the plan file is out of scope here). Record the split in the corrections log.
> - **Forbidden:** resolving a baseless-deferral finding by deferring it again, or marking it refuted without either implementing the work or producing a scheduled-MEU + source-cited *Basis*.

---

### Step 3: Create Corrections Plan (Orchestrator)

For each verified finding, specify the exact fix:

- **File**: absolute path
- **What to change**: before → after (diff or description)
- **Test approach**: what test to write/modify first (TDD discipline)
- **Why**: link back to finding # and severity

Group fixes by file. Update the corrections plan **in the project folder** (`docs/execution/plans/{date}-{project-slug}/implementation-plan.md`) — the single source of truth. **Never** create a `RequestFeedback:true` mirror artifact (GUARDRAILS SIGN 3, Layer 1 — that path triggers the auto-approval injection on harnesses with `injects_auto_approval: yes`). Applying code/test corrections inside an already-approved plan is reversible work and auto-proceeds (`AGENTS.md` §Hard Gates); it needs no separate approval gate — the execution-critical-review re-dispatch is what re-validates the fixes.

---

### Step 4: Execute Corrections (Coder)

Apply all fixes using TDD discipline:

1. **Tests first**: write/update tests that reproduce the finding
2. **Confirm red**: verify tests fail before the fix
3. **Fix production code**: make tests pass
4. Read the exact lines before editing (get current line numbers)
5. Apply fixes bottom-to-top within each file
6. Multiple non-adjacent edits in the same file → single edit call

---

### Step 5: Verify Corrections (Tester)

Re-run the verification commands from Step 2 to confirm all findings are resolved.

### Step 5b: Evidence Refresh

After ALL corrections are applied, re-run every validation command and update the handoff with fresh counts:

```powershell
# Python projects
uv run pytest tests/ --tb=no -q        # Fresh regression total
uv run pyright <touched-packages>       # Type safety
uv run ruff check <touched-files>       # Lint

# TypeScript projects (when scaffolded)
npx vitest run                          # Fresh test total
npx tsc --noEmit                        # Type safety
npx eslint src/ --max-warnings 0        # Lint
```

Update the handoff with fresh counts — stale counts from earlier in the session are a recurring finding category.

### Step 5c: Cross-Doc Sweep

If any correction changed a contract or architectural pattern:

```powershell
# Search for old pattern across all canonical docs
rg -n -i "<old-pattern>" packages/ tests/ docs/build-plan/ docs/execution/
```

Update all references. Document: "Cross-doc sweep: N files checked, M updated."

### Step 6: Write Handoff (Documenter — NOT Reviewer)

> [!CAUTION]
> **Self-Approval Prohibition.** The corrections agent is the implementer (coder role). It MUST NOT set the verdict to `approved`. Only a subsequent `/execution-critical-review` pass — run by the reviewer role — may set `approved`. The corrections agent sets `corrections_applied` to signal readiness for re-review.

Update the same canonical implementation-critical-review handoff in `.agent/context/handoffs/`:

- append a dated `Corrections Applied` section
- include plan summary, diffs/changes made, test results, and verification results
- set verdict to `corrections_applied` (never `approved` — that requires an independent reviewer pass)
- keep the full review thread in that single file
- update frontmatter `verdict:` field to `corrections_applied`

---

### Step 7: Completion Timestamp (Mandatory Exit Gate)

> [!IMPORTANT]
> **Context-rot guard.** Re-read this workflow file before proceeding.
> If you are resuming after context truncation, this step will not exist in your context unless you re-read.

The **very last line** of the agent's chat response must be the timestamp skill output, copied verbatim.

This is a hard exit requirement for every `/execution-corrections` response, including short correction summaries.

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
4. **TDD discipline is mandatory.** Tests first, implementation after. Never modify tests to make them pass.
5. **User approval required before execution.** Plan → approve → execute → verify.
6. **Resolve the canonical review first.** Work from `*-implementation-critical-review.md` and update that same file.
7. **Fix general, not specific.** Search for ALL instances of the same category across similar files.
8. **Never touch plan documents or workflow files.** If a finding requires plan changes, defer to `/plan-corrections`.
9. **Never self-approve.** The corrections agent MUST NOT set the review verdict to `approved`. Use `corrections_applied` to signal readiness for re-review. Only `/execution-critical-review` (reviewer role) may issue `approved`.

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
2. `/execution-critical-review` → review completed implementation work
3. `/execution-corrections` → resolve implementation-review findings (this workflow)
4. `/plan-critical-review` → review plans before implementation

When to switch:

- Use `/execution-critical-review` first to **produce** the review findings.
- Use this workflow (`/execution-corrections`) to **resolve** implementation-level findings.
- Use `/plan-corrections` for plan document and workflow corrections.

## HARD STOP

> [!CAUTION]
> **Do NOT autonomously chain into `/execution-critical-review`, `/plan-corrections`, or any other workflow after completing corrections.** You MUST stop here and report the canonical review handoff path to the user. The user decides what happens next.

**Workflow complete.** Report the handoff path and wait for user direction.
