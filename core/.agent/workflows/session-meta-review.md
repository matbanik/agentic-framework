---
description: Review a session MD file to identify human prompts, agentic actions, and responses — then use sequential thinking + web research to surface friction points and generate improvement rules.
---

# Session Meta-Review Workflow

Use this workflow to perform a structured retrospective on any session — conversation logs, task files, reflection files, or session digests — to identify what made it slow, ambiguous, or high-friction, and to generate concrete improvement rules for future sessions.

This is the workflow for prompts like:

- "Review yesterday's session and find friction points"
- "Meta-review the last conversation log"
- "Analyze this session and give me improvement rules"
- "What went wrong with this interaction pattern?"

// turbo-all
// NOTE: turbo-all sets SafeToAutoRun=true for non-destructive reads (Get-Content, rg, etc.).
// Never auto-commit per AGENTS.md §Commits.

---

## Prerequisites

Read these files:

1. `AGENTS.md`
2. `.agent/context/current-focus.md`
3. `.agent/skills/session-meta-review/SKILL.md` — friction taxonomy, segment detection patterns, sequential thinking template, web research query bank

---

## Role Sequence

1. `parser` — locate and segment the session into labeled turns
2. `analyst` — apply sequential thinking to categorize friction (uses `sequentialthinking` MCP)
3. `researcher` — validate patterns against published internet experience (uses `search_web`)

> **No coder role.** This workflow produces findings and rules only — it does not modify source code. If rules imply code or workflow changes, route those through `/execution-session`, `/plan-corrections`, or `/execution-corrections`.

---

## Auto-Discovery (No User Input Required)

When no session path is provided, auto-discover in this order:

```powershell
# 1. Find the most recent session digest
# (check .agent/context/sessions/ for latest digest.md)

# 2. Find the most recent reflection file
Get-ChildItem docs/execution/reflections/*.md |
  Sort-Object LastWriteTime -Descending | Select-Object -First 3

# 3. Find the most recent task plan
Get-ChildItem docs/execution/plans/ -Directory |
  Sort-Object LastWriteTime -Descending | Select-Object -First 3

# 4. Load the conversation brain task.md and implementation_plan.md
# (from C:\Users\{user}\.gemini\antigravity\brain\{conversation-id}\)
```

Auto-discovery selects the **most recent session** unless the user provides an explicit path.

---

## Step 1: Locate and Load Session Artifacts (Parser)

Identify and load the artifacts that represent the session:

| Artifact | Location | Priority |
|----------|----------|----------|
| Session digest | `.agent/context/sessions/{conversation-id}/digest.md` | High |
| Reflection file | `docs/execution/reflections/{YYYY-MM-DD}-{slug}-reflection.md` | High |
| Task file | `docs/execution/plans/{YYYY-MM-DD}-{slug}/task.md` | Medium |
| Implementation plan | `docs/execution/plans/{YYYY-MM-DD}-{slug}/implementation-plan.md` | Medium |
| Handoff artifact | `.agent/context/handoffs/{slug}.md` | Medium |
| Brain task.md | `{appDataDir}/brain/{conversation-id}/task.md` | Low |

Load at minimum one High-priority artifact. If none exists, load all Medium-priority artifacts.

Define the **session scope**:
- Date/time range
- MEUs or topics covered
- Agent roles used
- Outcome (approved / changes_required / incomplete)

---

## Step 2: Parse Interaction Segments (Parser)

Extract and label each distinct turn in the session. Use the segment taxonomy from `.agent/skills/session-meta-review/SKILL.md §Segment Taxonomy`.

For each segment, record:

| Field | Description |
|-------|-------------|
| `seq` | Sequential index within the session |
| `type` | `HUMAN_PROMPT` / `AGENT_PLAN` / `AGENT_TOOL_CALL` / `TOOL_OUTPUT` / `AGENT_RESPONSE` / `MODE_SWITCH` |
| `summary` | 1-sentence description of the content |
| `friction_signals` | Any of: vague intent, repeated clarification, tool retry, long gap, scope change, error |
| `word_count` | Approximate length |

Produce a **Segment Table** — this is the primary input to the analyst step.

### Detection Heuristics

Apply heuristics from the skill file to flag high-friction segments automatically:

- `HUMAN_PROMPT` with > 3 scope pivots or > 2 re-asks → `vague_intent`
- `AGENT_TOOL_CALL` repeated > 2× with same tool and arguments → `tool_retry_loop`
- `AGENT_RESPONSE` that triggered a follow-up human correction → `misaligned_response`
- `MODE_SWITCH` from EXECUTION → PLANNING mid-task → `unexpected_scope_change`
- `TOOL_OUTPUT` ignored or not referenced in the next `AGENT_RESPONSE` → `context_waste`

---

## Step 3: Sequential Thinking Analysis (Analyst)

Invoke the `sequentialthinking` MCP to perform structured multi-step analysis. Use the pre-scaffolded template from `.agent/skills/session-meta-review/SKILL.md §Sequential Thinking Template`.

The analysis decomposes friction across five categories:

| Category | Key Questions |
|----------|---------------|
| **Prompt Clarity** | Were human prompts specific enough? Were goals, constraints, and output format stated? |
| **Context Load** | Was the agent over- or under-loaded with context? Were relevant files missing? |
| **Tool Efficiency** | Were tools called redundantly? Were tool outputs used effectively? |
| **Verification Gaps** | Were claims verified against actual file state? Were tests or commands run at the right moment? |
| **Communication Quality** | Did the agent surface blockers promptly? Were decisions explained? Was handoff right-sized? |

For each category with findings, the `sequentialthinking` analysis should:

1. State the pattern observed (citing segment `seq` numbers)
2. Estimate severity: High / Medium / Low
3. Propose a root cause hypothesis
4. Allow for revision if a later thought contradicts the earlier hypothesis
5. Conclude with a single-sentence finding

> Use `isRevision: true` and `revisesThought: N` freely as you encounter contradictions.
> Adjust `totalThoughts` up if patterns require more decomposition.

Produce a **Friction Report** with findings ranked by severity.

---

## Step 4: Web Research Validation (Researcher)

For each `High` or `Medium` friction finding, validate the proposed mitigation against published internet experience.

Use `search_web` with queries from `.agent/skills/session-meta-review/SKILL.md §Web Research Query Bank`. Prefer `engine: tavily` with `search_depth: basic` for speed.

For each finding:

1. Run 1–2 targeted searches using the mapped query template
2. Extract the relevant snippet or principle (max 2–3 sentences)
3. Attach the source URL and title to the finding as `external_evidence`
4. Adjust the severity or mitigation if external evidence contradicts the hypothesis

> If no relevant external evidence is found for a finding, note it as `evidence: none found` and keep the severity unchanged.

---

## Step 5: Synthesize Improvement Rules (Synthesizer)

From the Friction Report + web evidence, generate 3–7 concrete improvement rules in the format used by `execution-session.md §5c`:

```
RULE-{N}: {description — actionable, specific, single behavior}
CATEGORY: {Prompt Clarity | Context Load | Tool Efficiency | Verification Gaps | Communication Quality}
SOURCE: {which friction signal led to this — cite segment seq}
EVIDENCE: {external source URL or "internal pattern only"}
EXAMPLE:
  BEFORE: {behavior that caused friction}
  AFTER:  {improved behavior}
```

### Output Destinations

Save the synthesized output to:

1. **Reflection file** — only if a reflection file exists for the session AND the user approves:
   Append a new `## Meta-Review Addendum — {YYYY-MM-DD}` section with the RULE-{N} set after the existing `## Next Session Design Rules` section.

Present the RULE-{N} set to the human for validation before appending to any file.

---

## Step 6: Aggregate Telemetry Cadence (every ~5–10 sessions)

> Cadence gate (AC-3.3). The per-session friction review above is qualitative; this step is the
> quantitative roll-up that turns the reflection corpus into a single report instead of a manual
> 13-agent audit. Run it when **≥5 new reflections** have accrued since the last dated report in
> `.agent/reports/` (cap ~10 — don't let the backlog grow unbounded).

**When to run:** count reflections newer than the latest `.agent/reports/coverage_*.md`. If ≥5, run; else skip and note "cadence not due".

```powershell
# Roll up the full reflection corpus into a dated report (md + json)
uv run python tools/aggregate_reflections.py `
  --input docs/execution/reflections `
  --registry .agent/schemas/registry.yaml `
  --output .agent/reports `
  *> {{RECEIPTS_DIR}}/agg-cadence.txt; Get-Content {{RECEIPTS_DIR}}/agg-cadence.txt
```

The dated report (`.agent/reports/coverage_{YYYYMMDD_HHMMSS}.md`) contains:
- **Corpus** — discovered / parsed / skipped counts (with reasoned skips)
- **Top sections by citation rate** + **Pruning candidates** (P0 never auto-pruned)
- **Statistical-power floor** (EI3 — `MIN_SECTION_SAMPLE`; thin sections labeled `INSUFFICIENT_DATA`, not pruned)
- **Section-id vocabulary** (AC-1.4 — unknown/normalized ids)
- **Finding categories** (AC-2.1), **Review-round churn** (AC-2.2), **Effort & delegation** (AC-2.3)

**Act on it:** surface `PRUNING_CANDIDATE` / `RAREBUT_DECISIVE` / `INVESTIGATE_DECAY` rows and the
delegation candidates to the human via `/plan-corrections` — never auto-prune (P0 safety). The
aggregator only *flags*; the human decides. (Rows labeled `INSUFFICIENT_DATA` are NOT surfaced for
action — they are below the statistical-power floor.)

**Close the loop (EI5 — mandatory):** for **each** recommendation surfaced above, after the human
decides, append a disposition row to `.agent/reports/action-log.md` so the report→decision→outcome
loop is recorded (the previous telemetry attempt died precisely because the report was write-only):

```powershell
uv run python tools/append_action_log.py `
  --date {YYYY-MM-DD} `
  --report coverage_{YYYYMMDD_HHMMSS}.md `
  --recommendation {PRUNING_CANDIDATE|RAREBUT_DECISIVE|INVESTIGATE_DECAY|DELEGATION_CANDIDATE} `
  --section {section_id} `
  --disposition {acted|deferred|rejected} `
  --link-notes "{/plan-corrections link or rationale}" `
  *> {{RECEIPTS_DIR}}/action-log.txt; Get-Content {{RECEIPTS_DIR}}/action-log.txt
```

A cadence run is not complete until every surfaced recommendation has a disposition row in
`.agent/reports/action-log.md`.

---

## Hard Rules

1. **Never fix issues during this workflow.** Produce findings and rules only — route implementation changes to `/execution-session`, `/plan-corrections`, or `/execution-corrections`.
2. **Never append rules to a reflection file without human approval.** Always present first via `notify_user`.
3. **Sequential thinking must run for at least 5 thoughts.** Shallow analysis (< 5 thoughts) produces imprecise rules.
4. **Web research is required for every High-severity finding.** Low-evidence High findings are not acceptable without a documented search attempt.
5. **Cite segment `seq` numbers** for every finding. Rules without evidence anchors are not traceable.
6. **Do not meta-review a meta-review.** Exclude `*meta-review*`, `*Memory/MetaReview*` artifacts from the session scope.

---

## Output Contract

Return to the user:

- **Session Scope Summary** — date, artifacts reviewed, outcome
- **Segment Table** — all labeled turns with friction signals
- **Friction Report** — ranked findings with category, severity, root cause, and external evidence
- **RULE-{N} set** — 3–7 improvement rules, ready for approval
- **Reflection appendix status** — `pending_approval`, `appended`, or `skipped (no reflection file)`

---

## Orchestration

This workflow fits naturally after these workflows:

- Run **after** `/execution-session` step 5 (Meta-Reflection) to deepen the friction analysis
- Run **after** `/plan-critical-review` or `/execution-critical-review` when a review cycle had unusually high friction
- Run **standalone** at any time as a weekly quality audit

Improvement rules generated here can feed back into:

- `/create-plan` — update session planning heuristics
- `/execution-session` §5c — append rules to the next session design
- `AGENTS.md` — elevate stable rules into permanent conventions
