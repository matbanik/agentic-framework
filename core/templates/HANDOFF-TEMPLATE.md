---
date: "{YYYY-MM-DD}"
project: "{project-slug}"
meu: "{MEU-ID}"
status: "draft"
action_required: "VALIDATE_AND_APPROVE"
template_version: "2.2"
verbosity: "standard"
plan_source: "docs/execution/plans/{YYYY-MM-DD}-{project-slug}/implementation-plan.md"
build_plan_section: "bp{NN}s{X.Y}"
agent: "{agent-name}"
reviewer: "{reviewer-name}"
predecessor: "{previous-handoff-filename or none}"
---

# Handoff: {YYYY-MM-DD}-{project-slug}-handoff

> **Status**: `draft` | `in_progress` | `complete` | `blocked`
> **Action Required**: `VALIDATE_AND_APPROVE` | `REVIEW_CORRECTIONS` | `EXECUTE`

---

## Scope

**MEU**: {MEU-ID} — {brief description}
**Build Plan Section**: {section reference}
**Predecessor**: {link to previous handoff or "none"}

---

## Acceptance Criteria

> **AC-table integrity (control C4).** Every AC-ID in the plan's AC table MUST appear here with a status — silently dropping an AC is a blocker, not a deferral. If an AC is not done, list it with a non-✅ status (and a row in Deferred Items naming the MEU it moved to). `Type` mirrors the plan: an `integration` AC's `Test(s)` cell must reference an integration/contract test, not a unit test (control C3).

| AC | Type | Description | Source | Test(s) | Status |
|----|------|-------------|--------|---------|--------|
| AC-1 | {unit\|integration} | {criterion} | {Spec\|Local Canon\|Research-backed\|Human-approved} | {test file:function} | ⬜ |
| AC-2 | {unit\|integration} | {criterion} | {source} | {test reference} | ⬜ |

<!-- CACHE BOUNDARY -->
<!-- Content above this line is stable across revision passes (KV cache prefix). -->
<!-- Content below this line changes between passes (evidence, results, corrections). -->

---

## Evidence

> **Test output rule**: Include only failing test names, assertion messages, and relevant stack frames. Summarize passing tests as `{N} passed`. See `.agent/docs/context-compression.md` for full rules.

### FAIL_TO_PASS

| Test | Red Output (hash/snippet) | Green Output | File:Line |
|------|--------------------------|--------------|-----------|
| {test_name} | {failure message} | {pass message} | {file:line} |

### Commands Executed

For each observation, include an `evidence.v1` JSON block from
`.agent/docs/output-evidence-policy.md` with command/procedure, cwd, scope, phase,
exit/result, tested_state and decisive pasted output. The table is a readable index,
not a substitute. Scratch paths appear only in commands. For final implementation
review include fresh full evidence bound to the independently obtained D6 state.

| Command | Exit Code | Key Output |
|---------|-----------|------------|
| `{exact command}` | 0 | {relevant output} |

### Quality Gate Results

```
pyright: X errors, Y warnings
ruff: X violations
pytest: X passed, Y failed
anti-placeholder: 0 matches
```

---

## Changed Files

> **Delta-only rule**: Show unified diff blocks (` ```diff `) for modifications. Do not inline full source code. See `.agent/docs/context-compression.md §Delta-Only Code Sections`.

| File | Action | Lines | Summary |
|------|--------|-------|---------|
| {path} | {new\|modified\|deleted} | {range} | {what changed} |

_For each modified file, include a fenced diff excerpt showing the key changes:_

```diff
 unchanged context line
-old_line_removed
+new_line_added
 unchanged context line
```

---

## Codex Validation Report

_Left blank for reviewer agent. Reviewer fills this section during `/validation-review`._

### Recheck Protocol

1. Read Scope + AC table
2. Verify each AC against Evidence section (file:line, not memory)
3. Independently probe the claimed behavior and compare decisive output
4. Verify the full gate is fresh and matches current D6 inputs; rerun if changed or unproven
5. Record findings below

### Findings

| # | Severity | Finding | File:Line | Recommendation | Status |
|---|----------|---------|-----------|----------------|--------|
| 1 | {High\|Medium\|Low} | {description} | {file:line} | {fix} | {open\|fixed} |

### Verdict

`{approved | changes_required}` — {rationale}

---

## Corrections Applied ({YYYY-MM-DD})

_Repeatable section. Add one per correction round._

**Findings resolved**: {N}/{N}

| # | Finding | Fix Applied | Verification |
|---|---------|-------------|--------------|
| 1 | {finding} | {fix} | {evidence} |

---

## Deferred Items

Blocked rows require `B-<row-id>`, a labeled follow-up link, and a matching block
under this section per the output evidence policy. Paste the actual command/nonzero
exit/error for an external blocker, or link the pending human decision. For D9=no,
use a scheduled domain task in place of a MEU. Unfinished implementation is not blocked.

_Optional. Skip this section if no items are deferred._

> **No-orphan-deferral (control C2).** A deferred AC/feature is invalid unless *Deferred-to MEU* names a MEU-ID **already scheduled** in the grouping / `meu-status.yaml`. "future-MEU", "next session", "wiring session" are NOT valid targets — register the MEU first, or the item stays in scope (it is a SKIP otherwise).

| Item | Reason | Deferred-to MEU (scheduled) | Follow-up |
|------|--------|-----------------------------|-----------|
| {item} | {blocked\|out-of-scope} | {MEU-ID} | {link to tracking} |

---

## History

| Event | Date | Agent | Detail |
|-------|------|-------|--------|
| Created | {date} | {agent} | Initial handoff |
| Submitted for review | {date} | {agent} | Sent to {reviewer} |
| Review complete | {date} | {reviewer} | Verdict: {verdict} |
| Corrections applied | {date} | {agent} | {N} findings resolved |
