# Issue Lifecycle Guide

> How issues are reported, tracked, triaged, planned, and resolved in the {{PROJECT_NAME_TITLE}} project.
> This guide covers the end-to-end lifecycle after all infrastructure from the
> [issue-triage-workflow-review](../../docs/execution/plans/) has been implemented.

---

## Overview

Issues flow through a structured pipeline with clear handoff points between human and AI:

```
REPORT → CAPTURE → VERIFY → TRIAGE → PLAN → IMPLEMENT → CLOSE
  👤        🤖       🤖      🤖+👤     🤖      🤖+🤖       👤
```

**Key principle:** Humans report problems and make decisions. AI does the heavy lifting of
verification, classification, planning, and implementation. Humans approve at each gate.

---

## 1. How a Human Reports an Issue

There are **three ways** a human can report an issue:

### Option A — Tell the Agent Directly (Simplest)

Just describe the problem in natural language during any session:

> "The MCP server strips trailing zeros from decimal prices"
>
> "The GUI screenshot button doesn't show a loading indicator"
>
> "Tax lot sync fails when there are no trades in the account"

The agent will use the **Issue Triage skill** (`.agent/skills/issue-triage/SKILL.md`)
to register it automatically. The agent runs:

```bash
uv run python tools/issue_triage.py add \
  --id "MCP-ZODSTRIP" \
  --title "MCP server strips trailing zeros from decimal prices" \
  --severity medium \
  --component mcp-server \
  --add-status open \
  --discovered 2026-06-25 \
  --root-cause "Zodiac schema coerces Decimal to float" \
  --blast-radius "All price displays lose precision"
```

The issue is written to `.agent/context/known-issues.yaml` (the single source of truth)
and the rendered `known-issues.md` is regenerated.

### Option B — File It Yourself in YAML

Edit `.agent/context/known-issues.yaml` directly and add an entry:

```yaml
- id: GUI-SCREENSHOT-NO-INDICATOR
  title: "Screenshot button has no loading indicator"
  severity: low
  component: ui
  status: open
  discovered: 2026-06-25
  root_cause: ""
  blast_radius: "User can't tell if screenshot is being captured"
  resolution_path: "Add spinner or progress indicator to screenshot button"
  notes: ""
```

Then regenerate the markdown:
```powershell
uv run python tools/issue_triage.py render
```

### Option C — The Agent Discovers It Automatically

The discovery scanner finds TODO/FIXME/HACK comments in source code:

```powershell
uv run python tools/issue_triage.py discover --dry-run   # preview
uv run python tools/issue_triage.py discover              # persist candidates
```

Candidates appear with `📋 candidate` status — they're hidden from the default
`known-issues.md` view until the human promotes them:

```powershell
uv run python tools/issue_triage.py promote DISC-001   # → open issue
uv run python tools/issue_triage.py dismiss DISC-002   # → dismissed (noise)
```

---

## 2. How a Human Requests an Issue Be Addressed

Once issues are registered, the human triggers the resolution pipeline by invoking
the **`/issue-triage`** workflow. Here's the step-by-step:

### Step 1 — Invoke Triage

```
/issue-triage
```

The agent reads `known-issues.yaml` and begins the triage workflow.

### Step 2 — Agent Runs Automated Deep Verification

The agent runs deep verification on every non-resolved issue — **without human input**:

```powershell
uv run python tools/issue_triage.py verify --deep
```

This automatically:
- ✅ Checks if referenced files still exist
- ✅ Scans for test coverage (does any test reference this issue ID?)
- ✅ Searches for fix indicators (has the code been patched?)
- ✅ Flags stale issues (not verified in 30+ days)
- ✅ Updates `verification.last_checked` timestamps

Issues that appear resolved get flagged. The agent may auto-archive them
or ask the human to confirm.

### Step 3 — Agent Classifies Each Issue

The agent classifies every active issue using this taxonomy:

| Category | Meaning | What Happens Next |
|----------|---------|-------------------|
| `MEU-NEW` | Needs a new work unit | Agent creates MEU scope |
| `MEU-EXPAND` | Fits in existing planned work | Agent links to MEU |
| `PLAN-NEW` | Needs an entirely new build plan section | Agent drafts section |
| `ARCH-DECISION` | Needs a design decision first | Human decides |
| `BLOCKED` | Blocked on other MEU completing | Wait |
| `WORKAROUND-OK` | Current workaround is fine | No action |
| `TECH-DEBT` | Low-priority cleanup | Batch later |
| `DEFER` | Low priority, defer | Backlog |
| `CLOSE` | Won't fix | Archive |

### Step 4 — Interactive Enrichment (🧑 Human Input)

For issues classified as `MEU-NEW`, `MEU-EXPAND`, or `ARCH-DECISION`, the agent
asks the human **targeted questions** — not open-ended "what do you think?" prompts:

```
┌─────────────────────────────────────────────────────────┐
│ Issue MCP-ZODSTRIP: MCP server strips trailing zeros    │
│                                                         │
│ How should this be scoped?                              │
│                                                         │
│  ○ Create new MEU in MCP Server phase                   │
│  ○ Expand existing MEU-308 (MCP data fidelity)          │
│  ○ Needs architecture decision first                    │
│  ○ Defer to later phase                                 │
│                                                         │
│                              [Submit]    [Skip]         │
└─────────────────────────────────────────────────────────┘
```

The agent also surfaces relationships:
- *"These 3 issues share the same component — one MEU or separate?"*
- *"Issue X blocks Y — escalate from Medium to High?"*
- *"Workaround for Z has been in place 3 months — still acceptable?"*

The human answers 5-10 targeted questions. This takes ~2 minutes, not 20.

### Step 5 — Agent Groups Issues into MEU Batches

The agent runs automated bucketing:

```powershell
uv run python tools/issue_triage.py bucket
```

This groups related actionable issues by component, priority, and overlap — producing
proposed project batches like:

```
Batch 1: "mcp-data-fidelity" (P1)
  ├── MCP-ZODSTRIP (medium, mcp-server)
  ├── MCP-DECIMAL-ROUND (medium, mcp-server)
  └── Proposed MEU: MEU-340 (expand MEU-308)

Batch 2: "gui-ux-polish" (P3)
  ├── GUI-SCREENSHOT-NO-INDICATOR (low, ui)
  ├── GUI-DARK-MODE-FLASH (low, ui)
  └── Proposed MEU: MEU-341 (new)
```

### Step 6 — Agent Generates Triage Output

```powershell
uv run python tools/issue_triage.py triage
```

This produces `.agent/context/triage-output.yaml` — the structured handoff that
feeds directly into `/session-grouping` and `/create-plan`.

### Step 7 — HARD STOP: Human Reviews and Approves

The agent presents the triage results and **stops**. It does NOT proceed to planning.

The human reviews:
- Proposed batches and their priorities
- Any architecture decisions needing input
- Verification findings (resolved issues, stale issues)

The human then says one of:
- ✅ *"Approved. Proceed with batch 1."*
- 🔄 *"Move issue X to batch 2 instead."*
- ❌ *"Defer batch 3 entirely."*

---

## 3. How Build Plans Are Created and Issues Resolved by AI

After the human approves triage batches, the agentic pipeline takes over:

### Phase A — Session Grouping

```
/session-grouping
```

The agent reads `triage-output.yaml` (not raw markdown) and groups approved batches
into implementation sessions — each session is a coherent project:

```
Session 1: "mcp-data-fidelity" → MEU-340
Session 2: "gui-ux-polish"     → MEU-341
```

### Phase B — Plan Creation

```
/create-plan
```

For each session, the agent:

1. **Reads** the batch scope from `triage-output.yaml`
2. **Researches** the codebase to understand what needs to change
3. **Writes** a full implementation plan with:
   - Acceptance criteria per issue
   - File-level change descriptions
   - Test plan
   - Verification commands
4. **Dispatches** the plan to an external reviewer (Codex `independent_reviewer`)
5. If `plan_to_exec_gate == human`, presents the plan to the human for an explicit go-ahead; if `reviewer-auto`, auto-continues once the reviewer returns `approved` (see `.agent/docs/harness-profiles.md`)

```
┌──────────────────────────────────────────────────┐
│  Implementation Plan: mcp-data-fidelity          │
│                                                  │
│  Issues addressed: MCP-ZODSTRIP, MCP-DECIMAL     │
│  MEU: MEU-340                                    │
│  Files: 4 modified, 1 new                        │
│  Tests: 12 planned                               │
│                                                  │
│  → Plan reviewed: independent_reviewer (approved)│
│  → human gate: awaiting your go-ahead            │
└──────────────────────────────────────────────────┘
```

### Phase C — TDD Implementation

After the human approves the plan:

```
/execution-session @implementation-plan.md @task.md
```

The agent follows strict TDD:

1. **Write tests FIRST** — each acceptance criterion becomes a failing test
2. **Run tests** — confirm they fail (Red phase)
3. **Implement** — write code to make tests pass (Green phase)
4. **Refactor** — clean up while keeping tests green
5. **Quality gate** — pyright + ruff + pytest + anti-placeholder scan

### Phase D — Automated Review

The agent dispatches its own work to an **independent reviewer** (Codex `independent_reviewer`):

```
/execution-critical-review
```

The reviewer:
- Verifies all acceptance criteria are met
- Audits test rigor
- Checks for missed edge cases
- Produces a verdict: `approved` or `changes_required`

If `changes_required`, the agent applies corrections and re-submits.
This loop continues until approved or a 6-round cap is reached.

### Phase E — Issue Closure

After implementation passes review:

1. The agent updates `known-issues.yaml`:
   ```yaml
   - id: MCP-ZODSTRIP
     status: resolved        # was: open
     resolved: 2026-06-26
   ```

2. The rendered `known-issues.md` is regenerated (issue moves to archive)
3. The MEU registry is updated to mark the MEU complete
4. A handoff document captures what changed, with full evidence

### Phase F — Human Confirms

The human reviews the commit and either:
- ✅ Approves the git commit/push
- 🔄 Requests adjustments

**The issue is only truly closed when the human approves the commit.**

---

## 4. How Known Issues Are Managed Day-to-Day

### Data Architecture

```
.agent/context/known-issues.yaml     ← SSOT (agents read/write this)
.agent/context/known-issues.md       ← Rendered view (humans read this)
.agent/context/known-issues-archive.md ← LEGACY pre-SSOT history (read-only)
```

### The YAML is the Single Source of Truth

Every issue has enforced schema fields:

```yaml
- id: MCP-ZODSTRIP                    # Unique ID (component prefix)
  title: "MCP server strips zeros"    # Short description
  severity: medium                    # critical | high | medium | low
  component: mcp-server               # core | infrastructure | api | ui | mcp-server
  status: open                        # open | in_progress | workaround | mitigated | resolved
  discovered: 2026-06-25              # ISO date
  root_cause: "Zod coerces Decimal"   # Why it happens
  blast_radius: "Price display wrong" # What's affected
  resolution_path: "Use z.string()"   # How to fix it
  verification:
    last_checked: 2026-06-25          # When last verified
    method: "grep for Decimal"        # How verified
    result: "Still present"           # What was found
  meu_links: [MEU-340]               # Linked work units
  related: [MCP-DECIMAL-ROUND]       # Related issues
  notes: ""                          # Free-form notes
```

### Querying Issues

Agents and humans can query issues programmatically:

```bash
# How many critical issues?
uv run python tools/issue_triage.py list --severity critical

# What's broken in the API?
uv run python tools/issue_triage.py list --component api --status open

# Full stats dashboard
uv run python tools/issue_triage.py stats

# Machine-readable output for scripts
uv run python tools/issue_triage.py list --json
```

### Verification (Staleness Detection)

Issues are automatically checked for staleness:

```bash
uv run python tools/issue_triage.py verify          # Flag issues not checked in 30+ days
uv run python tools/issue_triage.py verify --deep    # Also check file existence, test coverage
```

### Rendered Markdown View

The human-readable `known-issues.md` is **generated** from the YAML — never hand-edited:

```bash
uv run python tools/issue_triage.py render           # Regenerate markdown
uv run python tools/issue_triage.py render --check    # Check for drift (CI-safe)
```

The rendered view stays compact (~30-50 lines) because the YAML holds the detail.

### Status Lifecycle

```
candidate → open → in_progress → resolved
    │                    │
    ↓                    ↓
dismissed          workaround → mitigated → resolved
```

| Status | Icon | Meaning |
|--------|------|---------|
| `candidate` | 📋 | Auto-discovered, awaiting human review |
| `dismissed` | ❌ | False positive from discovery |
| `open` | ⬜ | Confirmed issue, not yet worked |
| `in_progress` | 🔵 | Actively being addressed |
| `workaround` | 🟡 | Temporary mitigation in place |
| `mitigated` | 🟢 | Partially addressed |
| `resolved` | ✅ | Fixed and verified |

---

## 5. Complete Pipeline Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    ISSUE LIFECYCLE                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  👤 HUMAN REPORTS                                               │
│  ├── "Fix this bug" (natural language to agent)                 │
│  ├── Direct YAML edit                                           │
│  └── Reviews auto-discovered candidates                         │
│       │                                                         │
│       ▼                                                         │
│  🤖 STRUCTURED CAPTURE                                          │
│  └── tools/issue_triage.py add                                  │
│      Schema enforced: id, severity, component, root_cause       │
│       │                                                         │
│       ▼                                                         │
│  🤖 AUTO-DISCOVERY (periodic)                                   │
│  └── tools/issue_triage.py discover                             │
│      Scans TODO/FIXME/HACK in source comments                   │
│      Creates candidates → human promotes or dismisses           │
│       │                                                         │
│       ▼                                                         │
│  👤 HUMAN INVOKES /issue-triage                                 │
│       │                                                         │
│       ▼                                                         │
│  🤖 AUTOMATED DEEP VERIFICATION (Step 1)                        │
│  └── verify --deep                                              │
│      File checks, test coverage, fix indicators, staleness      │
│       │                                                         │
│       ▼                                                         │
│  🤖 CLASSIFICATION (Steps 2-3)                                  │
│  └── Agent classifies using taxonomy                            │
│       │                                                         │
│       ▼                                                         │
│  👤 INTERACTIVE ENRICHMENT (Step 3.5)                           │
│  └── Agent asks targeted questions:                             │
│      "One MEU or three?" / "Escalate?" / "Still blocked?"       │
│       │                                                         │
│       ▼                                                         │
│  🤖 MEU BUCKETING (Step 5)                                      │
│  └── issue_triage.py bucket                                     │
│      Groups issues into project batches                         │
│       │                                                         │
│       ▼                                                         │
│  🤖 TRIAGE OUTPUT (Step 6)                                      │
│  └── issue_triage.py triage → triage-output.yaml                │
│       │                                                         │
│       ▼                                                         │
│  👤 HARD STOP — Human reviews & approves batches                │
│       │                                                         │
│       ▼                                                         │
│  🤖 SESSION GROUPING                                            │
│  └── /session-grouping reads triage-output.yaml                 │
│       │                                                         │
│       ▼                                                         │
│  🤖 PLAN CREATION                                               │
│  └── /create-plan → implementation plan + external review       │
│       │                                                         │
│       ▼                                                         │
│  👤 HUMAN APPROVES PLAN                                         │
│       │                                                         │
│       ▼                                                         │
│  🤖 TDD IMPLEMENTATION                                          │
│  └── /execution-session → tests first → implement → refactor    │
│       │                                                         │
│       ▼                                                         │
│  🤖 AUTOMATED REVIEW                                            │
│  └── /execution-critical-review (Codex `independent_reviewer`)  │
│      Corrections loop until approved                            │
│       │                                                         │
│       ▼                                                         │
│  🤖 ISSUE CLOSURE                                               │
│  └── known-issues.yaml: status → resolved                       │
│       │                                                         │
│       ▼                                                         │
│  👤 HUMAN APPROVES COMMIT                                       │
│                                                                 │
│  👤 = Human interaction point                                   │
│  🤖 = Fully automated by AI agent(s)                            │
└─────────────────────────────────────────────────────────────────┘
```

### Human Touchpoints (4 total)

| # | When | What the Human Does | Time Required |
|---|------|---------------------|---------------|
| 1 | **Report** | Describes the problem | 30 seconds |
| 2 | **Enrichment** | Answers 5-10 targeted questions | 2-3 minutes |
| 3 | **Approve Plan** | Reviews implementation plan | 5-10 minutes |
| 4 | **Approve Commit** | Reviews changes, approves push | 2-5 minutes |

Everything between these touchpoints is automated — verification, classification,
bucketing, triage output, session grouping, TDD implementation, and code review.

---

## 6. Quick Reference — Common Prompts

### Reporting Issues

| You Say | Agent Does |
|---------|-----------|
| *"The tax sync crashes on empty accounts"* | Registers issue with schema validation |
| *"There's a TODO in the MCP server about Zod stripping"* | Registers with component inference |
| *"Run the discovery scanner"* | Executes `discover --dry-run` and presents candidates |

### Requesting Triage

| You Say | Agent Does |
|---------|-----------|
| *"Run issue triage"* or `/issue-triage` | Full pipeline: verify → classify → enrich → bucket → report |
| *"How many open issues do we have?"* | Runs `issue_triage.py stats` |
| *"What's broken in the API?"* | Runs `issue_triage.py list --component api --status open` |
| *"Check if issues are stale"* | Runs `issue_triage.py verify --deep` |

### After Triage Approval

| You Say | Agent Does |
|---------|-----------|
| *"Approved. Plan batch 1."* | Runs `/session-grouping` → `/create-plan` for batch 1 |
| *"Defer batch 3"* | Marks those issues as `DEFER` in YAML |
| *"Proceed with the plan"* | Runs `/execution-session` with TDD implementation |
| *"Commit and push"* | Creates git commit with all changes |

---

## 7. Files at a Glance

| File | Purpose | Who Uses It |
|------|---------|------------|
| `.agent/context/known-issues.yaml` | Issue data (SSOT) | Agents read/write |
| `.agent/context/known-issues.md` | Rendered view | Humans read |
| `.agent/context/known-issues-archive.md` | *Legacy* pre-SSOT history | Reference only; never written |
| `.agent/context/triage-output.yaml` | Triage handoff (ephemeral) | Pipeline stages |
| `tools/issue_triage.py` | CLI tool | Agents + humans |
| `tools/issue_triage/model.py` | Schema + validation | Internal |
| `tools/issue_triage/discover.py` | TODO/FIXME/HACK scanner | Agents |
| `tools/issue_triage/verify.py` | Deep verification | Agents |
| `tools/issue_triage/render.py` | Markdown renderer | Agents |
| `tools/issue_triage/bucket.py` | MEU batch grouping | Agents |
| `tools/issue_triage/triage.py` | Triage output generator | Agents |
| `.agent/workflows/issue-triage.md` | Workflow definition | Agents |
| `.agent/skills/issue-triage/SKILL.md` | Skill reference | Agents |
