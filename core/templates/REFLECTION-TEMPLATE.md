---
date: "{YYYY-MM-DD}"
project: "{project-slug}"
meus: ["{MEU-ID-1}", "{MEU-ID-2}"]
plan_source: "docs/execution/plans/{YYYY-MM-DD}-{project-slug}/implementation-plan.md"
template_version: "2.0"
---

# {YYYY-MM-DD} Meta-Reflection

> **Date**: {YYYY-MM-DD}
> **MEU(s) Completed**: {list}
> **Plan Source**: {plan path}

---

## Execution Trace

### Friction Log

1. **What took longer than expected?**
   _Answer here_

2. **What instructions were ambiguous?**
   _Answer here_

3. **What instructions were unnecessary?**
   _Answer here_

4. **What was missing?**
   _Answer here_

5. **What did you do that wasn't in the prompt?**
   _Answer here_

### Quality Signal Log

6. **Which tests caught real bugs?**
   _Answer here_

7. **Which tests were trivially obvious?**
   _Answer here_

8. **Did pyright/ruff catch anything meaningful?**
   _Answer here_

### Workflow Signal Log

9. **Was the FIC useful as written?**
   _Answer here_

10. **Was the handoff template right-sized?**
    _Answer here_

11. **How many tool calls did this session take?**
    _Answer here_

12. **Which rows were delegated, to which subagent (harness + model), and did any delegated result need rework?**
    <!-- Delegation via `.agent/skills/subagent-delegation/SKILL.md` ({{PROJECT_NAME}}-builder / {{PROJECT_NAME}}-verifier). -->
    _Answer here_

---

## Pattern Extraction

### Patterns to KEEP
1. _Practice that worked well_
2. _Practice that worked well_

### Patterns to DROP
1. _Ceremony without payoff_

### Patterns to ADD
1. _Gap that caused problems_

### Calibration Adjustment
- Estimated time: ___
- Actual time: ___
- Adjusted estimate for similar MEUs: ___

---

## Next Session Design Rules

```
RULE-1: {description}
SOURCE: {signal}
EXAMPLE: {before → after}
```

```
RULE-2: {description}
SOURCE: {signal}
EXAMPLE: {before → after}
```

```
RULE-3: {description}
SOURCE: {signal}
EXAMPLE: {before → after}
```

---

## Next Day Outline

1. _Target MEU(s)_
2. _Scaffold changes needed_
3. _Patterns to bake in from today_
4. _Codex validation scope_
5. _Time estimate_
6. ...

---

## Efficiency Metrics

| Metric | Value |
|--------|-------|
| Total tool calls | ___ |
| Time to first green test | ___ |
| Tests added | ___ |
| Codex findings | ___ |
| Handoff Score (X/7) | ___ |
| Rule Adherence (%) | ___ |
| Prompt→commit time | ___ |

### Rules Sampled for Adherence Check

| Rule | Source | Followed? |
|------|--------|-----------|
| _{rule description}_ | AGENTS.md §X | Yes/No |
| _{rule description}_ | AGENTS.md §X | Yes/No |

---

## Instruction Coverage

<!-- Emit a single fenced YAML block matching .agent/schemas/reflection.v1.yaml -->
<!-- See AGENTS.md § Instruction Coverage Reflection for rules -->
<!-- NOTE 2026-07-21: token counts, environment, and implementor_model are retired
     (Antigravity-era telemetry; non-functional under Cursor/Claude Code). Do NOT emit them. -->

```yaml
schema: v1
session:
  id: "{conversation-id}"
  task_class: "{tdd|review|debug|refactor|security|planning|research|other}"
  outcome: "{success|partial|failed}"
sections:
  - id: "{section_id from registry.yaml}"
    cited: false
    influence: 0  # 0=ignored, 1=read-only, 2=shaped-output, 3=decisive
loaded:
  workflows: []
  roles: []
  skills: []
  refs: []
decisive_rules: []  # max 5 entries, format: "P{0-3}:{rule-id}"
conflicts: []       # log instruction conflicts; do NOT leave empty if any rule fought another
note: ""
# --- Anti-bloat / honesty nudges (AC-3.1/3.2) — fill these in, don't leave default ---
slim_candidate: []        # ≥1 section/rule that felt over-weight, redundant, or relocatable this session
overthinking_observed: false  # true if you over-edited correct output or manufactured low-value findings
# Optional structured signals (AC-2.2/2.3) — populate when a review loop ran:
# review_churn:
#   rounds_to_approval: { plan: 0, execution: 0 }
#   churned_findings: 0
#   finding_categories: {}  # controlled vocabulary — see docs/execution/metrics.md §Finding Categories
#   verdicts: {}            # e.g. { changes_required: 1, approved: 1 }
# meu_work_classes: []    # one of mechanical|correctness|mixed per MEU (delegation analysis)
```

> **De-flatter reminder (AC-3.1):** `slim_candidate`, `conflicts`, and any `influence: 0`
> sections are the most valuable telemetry — they prevent the corpus from becoming a
> wall of "everything was useful." Record at least one honest `slim_candidate` and any
> conflict you hit; do not flatter the instruction set.
