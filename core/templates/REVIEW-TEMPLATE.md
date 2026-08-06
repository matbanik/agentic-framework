---
date: "{YYYY-MM-DD}"
review_mode: "{plan | handoff | multi-handoff}"
target_plan: "docs/execution/plans/{plan-path}/implementation-plan.md"
verdict: "pending"
findings_count: 0
template_version: "2.1"
requested_verbosity: "standard"
agent: "{reviewer-agent}"
---

# Critical Review: {target-slug}

> **Review Mode**: `plan` | `handoff` | `multi-handoff`
> **Verdict**: `approved` | `changes_required`

---

## Scope

**Target**: {file path(s) under review}
**Review Type**: {plan review | handoff review | multi-handoff project review}
**Checklist Applied**: {IR | DR | PR | combination}

---

## Findings

| # | Severity | Finding | File:Line | Recommendation | Status |
|---|----------|---------|-----------|----------------|--------|
| 1 | {High\|Medium\|Low} | {description} | {file:line} | {fix} | {open\|fixed} |

---

## Checklist Results

### Information Retrieval (IR)

| Check | Result | Evidence |
|-------|--------|----------|
| All AC have source labels | {pass\|fail} | {detail} |
| Validation cells are exact commands | {pass\|fail} | {detail} |
| BUILD_PLAN audit row present | {pass\|fail} | {detail} |
| Post-MEU rows present (handoff, reflection, metrics) | {pass\|fail} | {detail} |

### Design Review (DR)

| Check | Result | Evidence |
|-------|--------|----------|
| Naming convention followed | {pass\|fail} | {detail} |
| Template version present | {pass\|fail} | {detail} |
| YAML frontmatter well-formed | {pass\|fail} | {detail} |

### Post-Implementation Review (PR)

| Check | Result | Evidence |
|-------|--------|----------|
| Evidence bundle complete | {pass\|fail} | {detail} |
| FAIL_TO_PASS table present | {pass\|fail} | {detail} |
| Commands independently runnable | {pass\|fail} | {detail} |
| Anti-placeholder scan clean | {pass\|fail} | {detail} |

---

## Verdict

`{approved | changes_required}` — {rationale}

---

## Recheck ({YYYY-MM-DD})

_Repeatable section. Add one per recheck round._

**Workflow**: `/planning-corrections` recheck
**Agent**: {reviewer-agent}

### Prior Pass Summary

| Finding | Prior Status | Recheck Result |
|---------|-------------|----------------|
| {finding} | {fixed\|open} | {✅ Fixed\|❌ Still open} |

### Confirmed Fixes

- {description with file:line reference}

### Remaining Findings

- **{Severity}** — {description with file:line reference}

### Verdict

`{approved | changes_required}` — {rationale}
