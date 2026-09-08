---
description: Review known-issues.yaml, verify issues are still reproducible, classify with interactive enrichment, bucket into MEUs, and generate triage-output.yaml for /session-grouping and /create-plan.
---

# Issue Triage Workflow

Use this workflow when known issues have accumulated and you need to determine which ones
require new MEUs, expanded MEU scope, new build-plan sections, or can be deferred/archived.
This is a **PLANNING-phase-only** workflow — it produces structured triage output, not implementation.

// turbo-all

## Prerequisites

Read these files in order:

1. `AGENTS.md`
2. `.agent/context/known-issues.yaml` (**SSOT** — managed by `tools/issue_triage.py`)
3. `.agent/context/known-issues-archive.md` (legacy pre-SSOT history; scan only — verify nothing was prematurely archived there before the YAML SSOT existed)
4. `.agent/context/meu-status.yaml` (SSOT — see `.agent/skills/meu-status/SKILL.md`)
5. `docs/build-plan/build-priority-matrix.md`
6. `.agent/context/current-focus.md`

> [!IMPORTANT]
> **Data source is `known-issues.yaml`, not `known-issues.md`.**
> The YAML file is the single source of truth. The markdown file is a rendered view,
> regenerated at the end via `issue_triage.py render`. All reads, writes, and updates
> during this workflow target the YAML SSOT.

## Classification Taxonomy

Every active issue must be classified into exactly one category:

| Code | Category | Action Required |
|------|----------|----------------|
| `MEU-NEW` | New MEU Required | Create new MEU(s) within an existing build-plan section |
| `MEU-EXPAND` | Expand Existing MEU | Add scope/subtasks to an already-planned (⬜/🟡) MEU |
| `PLAN-NEW` | New Build Plan Section | Write new build-plan file + register new MEUs in the registry |
| `UPSTREAM` | Upstream/External | No MEU action — blocked on third-party fix; track and monitor |
| `ARCH-DECISION` | Architecture Decision Needed | Needs design decision (ADR, human approval) before MEU scoping |
| `WORKAROUND-OK` | Workaround Sufficient | Current mitigation is adequate; no further work planned |
| `BLOCKED` | Blocked on Other Work | Will resolve naturally when a dependent MEU completes |
| `TECH-DEBT` | Technical Debt | Low-severity cleanup that can be batched into a debt-reduction project |
| `CONFIGURATION` | Configuration Change | Fix via config update, not code |
| `DOCUMENTATION` | Documentation Update | Fix via docs update, not code |
| `MONITORING` | Monitoring/Observability | Add monitoring, not a code fix |
| `DEFER` | Deferred | Low priority, defer to later |
| `CLOSE` | Close / Won't Fix | Issue is not worth addressing |
| `DESIGN-DECISION` | (Legacy) Design Decision | Legacy alias — prefer `ARCH-DECISION` for new classifications |

## Steps

### Step 0.5 — Discovery (Optional)

> [!TIP]
> **Run the discovery scanner before deep verification** to surface TODO/FIXME/HACK
> comments that may represent untracked issues. New findings are registered as
> `candidate` issues — hidden from the default rendered view until explicitly
> promoted.

```powershell
rtk uv run python tools/issue_triage.py discover --dry-run *> {{RECEIPTS_DIR}}/discover-scan.txt; Get-Content {{RECEIPTS_DIR}}/discover-scan.txt
```

Review the scan output:
- **New candidates**: TODO/FIXME/HACK comments not linked to existing issues
- **Linked to existing**: Comments referencing known issue IDs (already tracked)

To persist new candidates into the YAML SSOT (without `--dry-run`):
```powershell
rtk uv run python tools/issue_triage.py discover *> {{RECEIPTS_DIR}}/discover-persist.txt; Get-Content {{RECEIPTS_DIR}}/discover-persist.txt
```

After review, use `promote` and `dismiss` to handle candidates:
```powershell
# Promote a valid candidate to a real open issue
uv run python tools/issue_triage.py promote DISC-001

# Dismiss a false positive
uv run python tools/issue_triage.py dismiss DISC-002
```

> **Note:** Use `render --include-candidates` to see candidate issues in the
> rendered markdown view:
> ```powershell
> rtk uv run python tools/issue_triage.py render --include-candidates *> {{RECEIPTS_DIR}}/render-candidates.txt; Get-Content {{RECEIPTS_DIR}}/render-candidates.txt
> ```

### 1. Automated Deep Verification

> [!IMPORTANT]
> **Use `issue_triage.py verify --deep` instead of manual grep.**
> This runs file-existence checks, test-coverage scans, and updates `verification.last_checked`.

Run deep verification on all non-resolved issues:

```powershell
rtk uv run python tools/issue_triage.py verify --deep *> {{RECEIPTS_DIR}}/verify-deep.txt; Get-Content {{RECEIPTS_DIR}}/verify-deep.txt
```

Review the findings:
- **`file_missing`**: Resolution path no longer exists — issue may be stale or file was renamed
- **`no_test_coverage`**: No test references the issue ID — may need regression test
- **`fix_indicator_found`**: Code matching the fix pattern was found — issue may be resolved

For each finding, determine if the issue should be:
1. **Archived** (if clearly resolved) — update status to `resolved` in YAML
2. **Updated** (if partially addressed) — update notes/resolution_path
3. **Kept active** (if still reproducible) — no change

### 2. Inventory & Classify

Read the verified `known-issues.yaml` and classify each active (non-resolved) issue
using the taxonomy above and sequential thinking.

For each issue, answer the classification questions:

1. **Is it an upstream bug with no local fix?** → `UPSTREAM`
2. **Is the current workaround sufficient long-term?** → `WORKAROUND-OK`
3. **Is it blocked on unfinished MEU work?** → `BLOCKED` (identify which MEU)
4. **Does it need an architectural decision first?** → `ARCH-DECISION`
5. **Does an existing planned MEU already cover this?** → `MEU-EXPAND`
6. **Can it fit within an existing build-plan section?** → `MEU-NEW`
7. **Does it require an entirely new capability area?** → `PLAN-NEW`
8. **Is it low-severity cleanup?** → `TECH-DEBT`

Update the `category` and `priority` fields in `known-issues.yaml` as you classify:

```python
# Example: programmatic update via model.py
issue["category"] = "MEU-NEW"
issue["priority"] = "P1"
```

### 3. Cross-Reference with MEU Registry

For each `MEU-EXPAND` classification, identify the target MEU:

```powershell
uv run python tools/meu_status.py list --phase {phase} *> {{RECEIPTS_DIR}}/meu-search.txt; Get-Content {{RECEIPTS_DIR}}/meu-search.txt
```

For each `MEU-NEW` classification, identify the build-plan section it belongs to.
Update the `meu_links` field in `known-issues.yaml` for issues with identified MEU targets.

### 3.5. Interactive Enrichment

> [!IMPORTANT]
> **Bounded scope.** Interactive enrichment targets ONLY issues classified as
> `MEU-NEW`, `MEU-EXPAND`, or `ARCH-DECISION`. All other categories proceed
> without human input.

For each issue in the enrichment-eligible categories, present targeted questions
to the human reviewer:

**If your harness has a question-prompt tool** (e.g. Antigravity's `ask_question`
modal), use it; otherwise ask the user directly in chat, for
structured yes/no and multiple-choice questions:

```
ask_question:
  question: "Issue {ID}: {title} — How should this be scoped?"
  options:
    - "Create new MEU in {build-plan-section}"
    - "Expand existing MEU-{ID}"
    - "Needs architecture decision first"
    - "Defer to later phase"
```

**In Claude CLI / Codex CLI dispatches**: Use `request_user_input` or inline
numbered choice lists.

After receiving answers, write the enrichment data to the YAML SSOT:

```python
issue["enrichment"] = {
    "questions_asked": ["How should this be scoped?"],
    "answers": ["Create new MEU in section X"],
    "decided_by": "human",
}
```

Save the updated YAML after enrichment:
```powershell
# The agent writes enrichment data via model.py save()
```

### 4. Assess Resolution Priority

For all actionable issues (`MEU-NEW`, `MEU-EXPAND`, `PLAN-NEW`, `ARCH-DECISION`),
assign a resolution priority using this matrix:

| Severity \ Impact | Blocks Other Work | Standalone |
|---|---|---|
| **Critical** | P0 — Immediate | P1 — Next session |
| **High** | P1 — Next session | P2 — Near term |
| **Medium** | P2 — Near term | P3 — Backlog |
| **Low** | P3 — Backlog | P4 — Opportunistic |

"Blocks Other Work" means the issue prevents planned MEUs from proceeding or causes CI/test failures.

### 5. MEU Bucketing

> [!IMPORTANT]
> **Use `issue_triage.py bucket` to generate proposed batches.**
> This groups actionable issues by component and detects related-field overlaps.

```powershell
rtk uv run python tools/issue_triage.py bucket *> {{RECEIPTS_DIR}}/bucket-output.txt; Get-Content {{RECEIPTS_DIR}}/bucket-output.txt
```

Review the proposed batches:
- Verify batch sizing (2-5 MEUs per batch is the sweet spot)
- Confirm priority coherence (don't mix P0 and P4 in the same batch)
- Note duplicate warnings (overlapping `related` fields)

### 5.5. Conditional MEU Scoping Review

> [!IMPORTANT]
> **Dispatch to external reviewer ONLY when the batch proposes 3+ new MEUs.**
> For smaller batches, the triage agent's classification is sufficient.

If any batch contains 3 or more MEUs:

1. Dispatch to Codex CLI or Claude CLI for independent MEU scoping review
2. Include the batch details and the enrichment data from Step 3.5
3. Apply reviewer feedback to adjust batch composition

### 6. Generate Triage Output

> [!IMPORTANT]
> **Use `issue_triage.py triage` to generate structured output.**
> This creates the ephemeral `triage-output.yaml` that feeds `/session-grouping`.

```powershell
rtk uv run python tools/issue_triage.py triage --output .agent/context/triage-output.yaml *> {{RECEIPTS_DIR}}/triage-output-log.txt; Get-Content {{RECEIPTS_DIR}}/triage-output-log.txt
```

The generated `triage-output.yaml` contains:
- `archived`: resolved issues
- `actionable`: open issues with actionable categories
- `deferred`: issues marked for deferral
- `proposed_batches`: output of the bucketing step

### 7. Render Markdown View

Regenerate the human-readable `known-issues.md` from the updated YAML:

```powershell
rtk uv run python tools/issue_triage.py render *> {{RECEIPTS_DIR}}/render-output.txt; Get-Content {{RECEIPTS_DIR}}/render-output.txt
```

### 8. Present for Review — HARD STOP

> [!CAUTION]
> **MANDATORY HARD STOP — NO EXCEPTIONS.**
> After presenting the triage results, the agent MUST end its turn immediately.
> Do NOT proceed to create plans or execute any implementation.

Present the triage results with:

1. State: **"Issue triage complete. Awaiting your review before plan generation."**
2. Summarize verification findings from Step 1 (deep verify results)
3. List the proposed MEU batches from Step 5 with their priorities
4. Highlight any architecture decisions requiring human input
5. Reference the generated `triage-output.yaml` path
6. **END YOUR TURN.**

The user will:
- Review and approve/modify project batches
- Make architecture decisions
- Then invoke `/session-grouping` (which reads `triage-output.yaml`) or `/create-plan` directly

## Integration with `/session-grouping` and `/create-plan`

After triage is complete:

1. `/session-grouping` reads `triage-output.yaml` as its **preferred input**
   (falls back to `known-issues.yaml` if triage output doesn't exist)
2. Each approved batch from session grouping becomes input to `/create-plan`
3. During `/create-plan` Step 2, the agent reads the approved batch
4. The batch's issue-to-MEU mappings become the project scope
5. Standard `/create-plan` Steps 3–5 proceed normally

## Exit Criteria

- [ ] `issue_triage.py verify --deep` run with findings reviewed
- [ ] Verification evidence attached (deep verify output)
- [ ] All active issues classified with category and priority in YAML
- [ ] Enrichment data written to YAML for MEU-NEW/MEU-EXPAND/ARCH-DECISION issues
- [ ] Cross-referenced against MEU Status SSOT (no duplicate MEUs)
- [ ] Cross-referenced against build-priority-matrix.md (correct section placement)
- [ ] `triage-output.yaml` generated via `issue_triage.py triage`
- [ ] `known-issues.md` regenerated via `issue_triage.py render`
- [ ] Report presented to human with HARD STOP
