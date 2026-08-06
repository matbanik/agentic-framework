---
description: Determine the next MEU or MEU group to plan for execution. Reviews build plan, registry, codebase state, and dependency graph to recommend the highest-priority unblocked work with infrastructure-first ordering.
---

# Next Project Selection Workflow

Use this workflow when you need to determine **what to build next**. It reviews the build plan,
MEU registry, codebase state, and dependency graph to recommend the single best project to plan.
This is a **PLANNING-phase-only** workflow — it produces a recommendation, not an implementation plan.

The output feeds directly into `/create-plan`.

// turbo-all

## Design Principles

1. **Infrastructure before features** — underlying services, adapters, and data layers before GUI pages
2. **Dependency-first** — never recommend work whose prerequisites are incomplete
3. **Priority-ordered** — follow the P0 → P4 priority bands in `build-priority-matrix.md`
4. **Completeness-driven** — prefer finishing a partially-complete phase/section over starting a new one
5. **Right-sized** — recommend 2–5 MEUs per project batch (sweet spot for context efficiency)

## Prerequisites

Read these files in order:

1. `AGENTS.md`
2. `.agent/context/current-focus.md`
3. `.agent/context/known-issues.md`
4. `.agent/context/meu-status.yaml` (SSOT — see `.agent/skills/meu-status/SKILL.md`)
5. `docs/BUILD_PLAN.md` (hub — phase status tracker + MEU summary table)
6. `docs/build-plan/build-priority-matrix.md`

## Steps

### 1. Build the Completion Snapshot

Scan the MEU status SSOT to build a progress picture:

```powershell
# Summary statistics (total, completed, pending, in-progress counts)
uv run python tools/meu_status.py stats *> {{RECEIPTS_DIR}}/meu-stats.txt; Get-Content {{RECEIPTS_DIR}}/meu-stats.txt
```

```powershell
# Find all pending/in-progress MEUs
uv run python tools/meu_status.py list --status pending *> {{RECEIPTS_DIR}}/meu-pending.txt; Get-Content {{RECEIPTS_DIR}}/meu-pending.txt
uv run python tools/meu_status.py list --status in_progress *> {{RECEIPTS_DIR}}/meu-inprog.txt; Get-Content {{RECEIPTS_DIR}}/meu-inprog.txt
```

```powershell
# Check latest handoff for carry-forward context
Get-ChildItem .agent\context\handoffs\*.md | Sort-Object LastWriteTime -Descending | Select-Object -First 3 | Select-Object Name *> {{RECEIPTS_DIR}}/recent-handoffs.txt; Get-Content {{RECEIPTS_DIR}}/recent-handoffs.txt
```

From this, determine:
- Total completed vs remaining MEUs
- Which phases/sections have partial completion (these get priority)
- Any 🟡 (ready_for_review) or 🔵 (in-progress) MEUs that need resolution first

### 2. Identify Unblocked Candidates

Walk the build-priority-matrix.md in priority order (P0 → P1 → P1.5 → P2 → P2.5 → ... → P4).

Use the SSOT's `--unblocked` filter to identify MEUs that are pending with all dependencies approved:

```powershell
# Find unblocked MEUs, ordered by priority
uv run python tools/meu_status.py next --limit 20 *> {{RECEIPTS_DIR}}/next-unblocked.txt; Get-Content {{RECEIPTS_DIR}}/next-unblocked.txt
```

```powershell
# Filter by specific band
uv run python tools/meu_status.py list --status pending --unblocked --band P2 *> {{RECEIPTS_DIR}}/next-p2.txt; Get-Content {{RECEIPTS_DIR}}/next-p2.txt
```

```powershell
# Quick check: are there any pending MEUs in the highest-priority incomplete band?
Select-String -Path "docs\build-plan\build-priority-matrix.md" -Pattern "⬜|pending" *> {{RECEIPTS_DIR}}/matrix-pending.txt; Get-Content {{RECEIPTS_DIR}}/matrix-pending.txt | Select-Object -First 30
```

### 3. Validate Codebase Readiness

Run targeted checks to confirm the codebase is healthy and ready for new work:

```powershell
# Quick pytest smoke test (last 20 lines)
uv run pytest tests/unit/ -x --tb=line -q *> {{RECEIPTS_DIR}}/pytest-smoke.txt; Get-Content {{RECEIPTS_DIR}}/pytest-smoke.txt | Select-Object -Last 20
```

```powershell
# Check for uncommitted changes that might indicate unfinished work
git status --short *> {{RECEIPTS_DIR}}/git-status.txt; Get-Content {{RECEIPTS_DIR}}/git-status.txt | Select-Object -First 20
```

```powershell
# Verify no TODO/FIXME/NotImplementedError blockers in recently modified packages
rg "TODO|FIXME|NotImplementedError" packages/ --count *> {{RECEIPTS_DIR}}/todo-scan.txt; Get-Content {{RECEIPTS_DIR}}/todo-scan.txt
```

If tests are failing or there are unfinished items, note them — they may need resolution before
or as part of the next project.

### 4. Apply the Infrastructure-First Filter

For all unblocked candidates, apply this ordering heuristic:

```
Priority 1: Backend domain/infrastructure (entities, services, repos)
Priority 2: REST API endpoints
Priority 3: MCP tools
Priority 4: GUI components
Priority 5: Distribution / CI / Research items
```

Within each priority, prefer:
1. **Completing a partially-done section** over starting a new one
2. **Foundation work** that unblocks multiple downstream MEUs
3. **Lower matrix order numbers** (earlier = more foundational)

### 5. Score and Rank Candidates

For each candidate MEU group, evaluate using sequential thinking:

| Factor | Weight | How to Assess |
|--------|--------|---------------|
| **Priority band** | 30% | Lower P-number = higher score |
| **Unblock count** | 25% | How many downstream MEUs does this unblock? |
| **Phase completion** | 20% | Does this complete or nearly complete a phase/section? |
| **Infrastructure depth** | 15% | Backend > API > MCP > GUI > Distribution |
| **Complexity** | 10% | Prefer right-sized batches (S/M over L/XL) |

### 6. Verify Build Plan Spec Readiness

For the top-ranked candidate, read the relevant build-plan spec file(s):

```powershell
# List build plan files for the candidate section
Get-ChildItem docs\build-plan\*.md | Select-Object Name *> {{RECEIPTS_DIR}}/bp-files.txt; Get-Content {{RECEIPTS_DIR}}/bp-files.txt
```

Verify:
- [ ] The build plan section exists and has sufficient detail
- [ ] Acceptance criteria are derivable from the spec
- [ ] No known issues block this work
- [ ] Related indexes (input-index.md, output-index.md) have entries for this work (if applicable)

If the spec is insufficient, note what pre-build research is needed before planning can begin.

### 7. Generate Recommendation

Write the recommendation to **both** locations:

1. `.agent/context/next-project-recommendation.md` — project-side canonical copy
2. Agent workspace artifact — for UI rendering

The recommendation must include:

```markdown
# Next Project Recommendation — {YYYY-MM-DD}

## Recommended Project

- **Project slug:** `{slug}`
- **Priority band:** P{N}
- **MEUs included:** {list with IDs, slugs, and descriptions}
- **Execution order:** {dependency-ordered list}
- **Build plan section(s):** {file references}
- **Estimated complexity:** S / M / L

## Rationale

### Why This Project?
{Explain the infrastructure-first reasoning, dependency unblocking, and phase completion benefits}

### What It Unblocks
{List downstream MEUs and features that become available after this project}

### Phase Completion Impact
{Before: X/Y MEUs complete in phase Z → After: X+N/Y complete}

## Completion Snapshot

| Priority Band | Total | Done | Remaining | Next Unblocked |
|--------------|-------|------|-----------|----------------|

## Codebase Health Check
- Tests: {pass/fail count}
- Uncommitted changes: {yes/no + summary}
- TODO/FIXME count: {count}
- Known blockers: {list or "none"}

## Spec Readiness
- Build plan file: {path} — {sufficient / needs research}
- Pre-build research needed: {yes/no + topics}
- Known issues affecting this work: {list or "none"}

## Runner-Up Candidates

| Rank | Project | MEUs | Priority | Reason Not Selected |
|------|---------|------|----------|---------------------|

## Next Step

Invoke `/create-plan` to generate the implementation plan for `{slug}`.
```

### 8. Present for Review — HARD STOP

> [!CAUTION]
> **MANDATORY HARD STOP — NO EXCEPTIONS.**
> After presenting the recommendation, the agent MUST end its turn immediately.
> Do NOT proceed to create plans or execute any implementation.

Present the recommendation with:

1. State: **"Next project recommendation ready. Awaiting your review before plan generation."**
2. Summarize the recommended project and its rationale
3. List runner-up candidates for comparison
4. Highlight any spec gaps or pre-build research needs
5. **END YOUR TURN.**

The user will:
- Review and approve/modify the recommendation
- Then invoke `/create-plan` for the approved project

## Integration with `/create-plan`

After the recommendation is approved:

1. The user invokes `/create-plan`
2. During Step 2, the agent reads the approved recommendation
3. The recommendation's MEU list and execution order become the project scope
4. Standard `/create-plan` Steps 2A–5 proceed normally

## Exit Criteria

- [ ] MEU registry scanned — all statuses current
- [ ] Build priority matrix reviewed — priority ordering respected
- [ ] Dependency graph validated — no blocked MEUs recommended
- [ ] Codebase health verified (tests, git status, TODO scan)
- [ ] Infrastructure-first ordering applied
- [ ] Top candidate scored and justified
- [ ] Build plan spec readiness verified for top candidate
- [ ] Recommendation written to `.agent/context/next-project-recommendation.md`
- [ ] Report presented to human with HARD STOP
