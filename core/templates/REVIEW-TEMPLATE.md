---
date: "{YYYY-MM-DD}"
review_mode: "{plan | execution | discovery | handoff | multi-handoff}"
target_plan: "docs/execution/plans/{plan-path}/implementation-plan.md"
verdict: "pending"
findings_count: 0
template_version: "2.1"
requested_verbosity: "standard"
agent: "{reviewer-agent}"
---

# Critical Review: {target-slug}

> **Review Mode**: `plan` | `execution` | `discovery` | `handoff` | `multi-handoff`
> **Verdict**: `approved` | `changes_required`

---

## Scope

**Target**: {file path(s) under review}
**Review Type**: {plan review | execution review | discovery review | handoff review | multi-handoff project review}
**Checklist Applied**: {IR | DR | PR | combination}

---

## Findings

| # | Severity | Blocking | Kind | Finding | File:Line | Recommendation | Status |
|---|----------|----------|------|---------|-----------|----------------|--------|
| 1 | {Critical\|High\|Medium\|Low} | {yes\|no} | {behavior\|control-defeat\|clerical} | {description} | {file:line} | {fix} | {open\|fixed\|accepted_risk} |

> **`Blocking` is not `Severity`** (`review-verdict.schema.v2.json`). A finding can be
> Critical and non-blocking (real, but outside this loop's scope) or Medium and blocking
> (small, but it defeats a control). Only `Blocking: yes` gates approval, so an
> `approved` verdict MAY carry open rows marked `no` — record real observations here
> rather than demoting them to prose to empty the table.
>
> Fill the column. `validate_closeout_artifacts.py --approved-state-only` counts an open
> row as blocking unless the cell explicitly says `no`, so an unfilled cell refuses the
> approval rather than being waved through.
>
> `Kind: control-defeat` also needs a stable kebab-case **mechanism** slug — write it in
> the Finding cell as `mechanism: <slug>`. The slug names *how* a gate was defeated, not
> the individual manoeuvre, and it must be reused across rounds for the same weakness:
> three blocking control-defeat findings sharing one mechanism stop the loop, because at
> that point the mechanism is the defect.

---

## Checklist Results

### Information Retrieval (IR)

| Check | Result | Command | Exit | Evidence |
|-------|--------|---------|------|----------|
| All AC have source labels | {pass\|fail\|partial\|n/a} | `{exact command}` | {0} | {detail} |
| Validation cells are exact commands | {pass\|fail\|partial\|n/a} | `{exact command}` | {0} | {detail} |
| BUILD_PLAN audit row present | {pass\|fail\|partial\|n/a} | `{exact command}` | {0} | {detail} |
| Post-MEU rows present (handoff, reflection, metrics) | {pass\|fail\|partial\|n/a} | `{exact command}` | {0} | {detail} |

### Design Review (DR)

| Check | Result | Command | Exit | Evidence |
|-------|--------|---------|------|----------|
| Naming convention followed | {pass\|fail\|partial\|n/a} | `{exact command}` | {0} | {detail} |
| Template version present | {pass\|fail\|partial\|n/a} | `{exact command}` | {0} | {detail} |
| YAML frontmatter well-formed | {pass\|fail\|partial\|n/a} | `{exact command}` | {0} | {detail} |

### Post-Implementation Review (PR)

| Check | Result | Command | Exit | Evidence |
|-------|--------|---------|------|----------|
| Evidence bundle complete | {pass\|fail\|partial\|n/a} | `{exact command}` | {0} | {detail} |
| FAIL_TO_PASS table present | {pass\|fail\|partial\|n/a} | `{exact command}` | {0} | {detail} |
| Commands independently runnable | {pass\|fail\|partial\|n/a} | `{exact command}` | {0} | {detail} |
| Anti-placeholder scan clean | {pass\|fail\|partial\|n/a} | `{exact command}` | {0} | {detail} |

---

## Verdict

`{approved | changes_required}` — {rationale}

> **The two verdicts have opposite requirements** (`review-verdict.schema.v2.json`):
> `approved` may carry findings but no **blocking** one; `changes_required` must name at
> least one blocking finding. A refusal with nothing blocking behind it is unactionable
> — in practice it records reluctance rather than a defect — and `review_ledger.py record`
> rejects it, so it consumes a round without producing one.
>
> A `Result` of `pass`/`fail`/`partial` above requires the `Command` that produced it;
> only `n/a` may leave it empty. An asserted outcome with no command behind it is prose,
> and `Exit` is recorded separately because exit 0 from a wrapper means the wrapper
> finished, not that the check ran.

---

## Recheck ({YYYY-MM-DD})

_Repeatable section. Add one per recheck round — **in this file**, under exactly this
`## Recheck` heading. It is the round counter: `validate_closeout_artifacts.py` reads the
round number as `1 + the number of "## Recheck" headings here`. A per-round file, or a
differently-worded heading, silently resets the count to 1 and defeats the cap._

**Workflow**: `/planning-corrections` recheck
**Agent**: {reviewer-agent}

### Prior Pass Summary

| Finding | Prior Status | Recheck Result |
|---------|-------------|----------------|
| {finding} | {fixed\|open} | {✅ Fixed\|❌ Still open} |

### Confirmed Fixes

- {description with file:line reference}

### Remaining Findings

- **{Severity}** / blocking: {yes|no} — {description with file:line reference}
  (carry the same finding id and `mechanism:` slug forward; a mechanism that recurs
  across rounds is the finding)

### Verdict

`{approved | changes_required}` — {rationale}
