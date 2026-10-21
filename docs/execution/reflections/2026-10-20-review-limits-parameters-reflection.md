---
date: "2026-10-21"
project: "2026-10-20-review-limits-parameters"
meus: []
plan_source: "docs/execution/plans/2026-10-20-review-limits-parameters/implementation-plan.md"
template_version: "2.0"
---

# 2026-10-21 Meta-Reflection

> **Date**: 2026-10-21
> **MEU(s) Completed**: none (`meus: []`)
> **Plan Source**: docs/execution/plans/2026-10-20-review-limits-parameters/implementation-plan.md

---

## Execution Trace

### Friction Log

1. **What took longer than expected?**
   The plan-review loop. It took 7 rounds, against a base of 3, and the human bought 5 more rounds and raised the token cap to 150M. Round 2 approved, then the D-1 amendment ("limit should be off as well") reopened it. Rounds 3 to 6 were all about the verification gates themselves: a Pester gate that passed a discovery failure, then a failed `AfterAll`, and an interrupted pytest run that was accepted as complete. The execution loop took 2 rounds. Three full H1-2 gate runs took about 50 minutes each.

2. **What instructions were ambiguous?**
   AC-13 says `begin` opens a loosened loop "only when `limits-check` passes". It did not say that the block `begin` installs must be the block that `limits-check` verified. The slug-only call satisfied the wording and left F-001 open.

3. **What instructions were unnecessary?**
   Row 5c's verbatim `python -c` one-liner could not run under pwsh (D-15). The checks it named were the point; the inline form only added quoting failures.

4. **What was missing?**
   A dispatch-wrapper note that `-OutputDir/<DispatchId>` must not exist beforehand. I pre-created it to hold the rolling-review base file, and the wrapper refused before any round was used. Also missing: a non-Windows check in the plan for every new test file that imports `run_parameters_fixtures`. H1-2 run 1 found it the slow way.

5. **What did you do that wasn't in the prompt?**
   - Built a separate dispatch stage (`stage-exec-2026-10-21`), because the plan's `rl-stage` points RECEIPTS_DIR at a sub-folder.
   - Added three pinned `NOT_A_PROMISE` entries to `scripts/refcheck.py` (D-14).
   - Transcribed the F-001 red output from the console into a receipt, because the red run was not redirected to a file.

### Quality Signal Log

6. **Which tests caught real bugs?**
   - `test_retained_python_tests_collect` caught the non-Windows install keeping `test_review_limits_audit.py` without its fixtures.
   - The reviewer's same-slug probe caught F-001. `test_begin_refuses_a_same_slug_ac_file_with_other_limits` now pins it with the real verifier.
   - `refcheck` caught this handoff's own file-colon-test cells.

7. **Which tests were trivially obvious?**
   `test_loosened_block_needs_limits_check` in its first form: its stub returned `(0, "OK")`, so it proved only that a refusal is propagated. That is how F-001 got through.

8. **Did pyright/ruff catch anything meaningful?**
   Neither is in this package's gate; the §1 static gate is pyflakes, which found 0 issues.

### Workflow Signal Log

9. **Was the FIC useful as written?**
   Yes for AC-1..AC-12 and AC-14..AC-21. AC-13 was the weak binding: see Friction 2.

10. **Was the handoff template right-sized?**
    Yes. The evidence.v1 records, generated from receipts by a script, survived three regenerations without hand edits. The Corrections Applied section fit F-001 directly.

11. **How many tool calls did this session take?**
    1341 tool calls in the main session transcript, across planning, 7 plan-review rounds, execution and 2 execution-review rounds. There were 14 automatic compactions.

12. **Which rows were delegated, to which subagent (harness + model), and did any delegated result need rework?**
    Only the independent reviews. Codex CLI `gpt-6.1-sol` (high reasoning effort) ran through the ledger-bound `Invoke-CodexDispatch.ps1` wrapper, with AuthorVendor anthropic: 7 plan rounds and 2 execution rounds. Execution round 1 required product rework (F-001); round 2 approved. No build row was delegated.

### Decisions Log

| ID | Stage | Question | Resolution | Chosen | Source tag | Reasoning (why this; why the alternatives lost) | Human ref |
|----|-------|----------|------------|--------|------------|--------------------------------------------------|-----------|
| D-1 | planning | Does token budgets "off" also turn off the USD caps on scheduled credits runs? | human | Yes; under off a manifest may omit its USD caps, under on or with no repo file they stay required | Human-approved | The human ruled it; implementation-plan.md Decision Log D-1 | USER_EXPLICIT 2026-10-20 "1. limit should be off as well" |
| D-2 | planning | May a plan be less strict than the setup choice? | human | Only through a value in a human-typed offer that the bound authorization verifies; otherwise tighten-only | Human-approved | The human ruled it; implementation-plan.md D-2 | USER_EXPLICIT 2026-10-20 "1. yes 2. yes proceed with create plan" |
| D-3 | planning | Where does the setup choice live? | autonomous | `.agent/review-limits.json` with all five modes plus the token_budgets switch | Local Canon | One file read by the ledger and credits_state; implementation-plan.md D-3 | — |
| D-4 | planning | Does the plan block store "repo" or numbers? | autonomous | Concrete numbers plus a basis field | Local Canon | A later repo change cannot silently move an approved plan; implementation-plan.md D-4 | — |
| D-5 | planning | run_parameters key or sibling block? | autonomous | A sibling review_limits block; only loosening goes through limits-check | Local Canon | Tightening needs no authorization; implementation-plan.md D-5 | — |
| D-6 | planning | Pin review-limits.json in the run-parameters policy? | autonomous | No; the ledger records its sha256 in limits_source | Local Canon | Pinning changes every adopter's activation; implementation-plan.md D-6 | — |
| D-7 | planning | How is "off" represented? | autonomous | The string off; 0 or null refused (exit 3); continue --tokens on an off loop refused | Local Canon | 0/null are ambiguous between unlimited and none; implementation-plan.md D-7 | — |
| D-8 | planning | Where does the final audit get its execution round cap? | autonomous | The exec ledger's rounds_allowed(); missing ledger with a task block refused | Local Canon | Closes plan-review F-002's bypass; implementation-plan.md D-8 | — |
| D-9 | planning | Behaviour off Windows or with run parameters disabled? | autonomous | Defaults and tightening work; a loosened block is refused | Local Canon | limits-check needs the Windows verb; fail closed; implementation-plan.md D-9 | — |
| D-10 | planning | Does this plan carry a run_parameters block? | autonomous | No; the authorization is manual | Local Canon | implementation-plan.md D-10 | — |
| D-11 | planning | Does a present cap still bind under off, and does switching back on reach a registered run? | autonomous | A present cap binds; each uncapped admission re-reads the switch and on rejects with caps_required | Local Canon | implementation-plan.md D-11 | — |
| D-12 | planning | Exposure of an uncapped segment with an unknown cost? | autonomous | Exposure 0 with cost_known 0 | Local Canon | implementation-plan.md D-12 | — |
| D-13 | planning | How does credits_state.py read the switch? | autonomous | review_ledger.load_repo_limits(root) from the same tools folder | Local Canon | One parser; implementation-plan.md D-13 | — |
| D-14 | execution | How to pass AC-20 with 3 unresolved refs in approved records? | autonomous | Three pinned NOT_A_PROMISE entries in scripts/refcheck.py | Local Canon | Editing approved records rewrites history; pinned entries fail again if the line moves; the round-1 reviewer accepted it | — |
| D-15 | execution | Row 5c's python -c fails to quote under pwsh | autonomous | Run the same four checks from a script; a negative run against d698342 exits 1 | Local Canon | The checks are the requirement, not the inline form | — |
| D-16 | execution | Docs said a caps_required run resumes; the code cannot re-register a started run | autonomous | Docs follow the code: register a new run with caps, or switch back to off | Local Canon | Docs must describe the store's behaviour; re-registration was out of scope | — |
| D-17 | execution | Add the /2 offer schema and review_ledger.py to REQUIRED_COMPONENTS? | autonomous | No, as planned; raised to the reviewer | Local Canon | Changes every adopter's activation policy; out of approved scope | — |
| D-18 | execution | How should begin bind a loosened block to the verified one (F-001)? | autonomous | Compare the review_limits limits-check printed with the block installed, key for key | Local Canon | Path equality depends on how REPO_ROOT and the git top-level line up; value equality binds wherever the file lives; round 2 approved | — |
| D-19 | plan-review | Token budget for the plan-review loop | human | Triple the token budget and continue | Human-approved | The human bought it with continue | USER_EXPLICIT 2026-10-20 "Tripple the token budget and continue running" |
| D-20 | plan-review | Record round 3, and whether to grant another round | human | Record r3 and grant 1 round | Human-approved | AskUserQuestion answer | USER_EXPLICIT 2026-10-20 "Record r3, grant 1 round (Recommended)" |
| D-21 | plan-review | How to make the pytest gate fail on an interrupted run (F-010) | human | Install psutil and use the plain gates (pytest's own exit status) | Human-approved | AskUserQuestion answer | USER_EXPLICIT 2026-10-20 "Install psutil, plain gates (Recommended)" |
| D-22 | plan-review | More plan-review rounds | human | 3 more rounds and a 150M total token limit | Human-approved | The human bought it with continue | USER_EXPLICIT 2026-10-20 "add 3 more rounds and increase token limit to 150M total" |

---

## Pattern Extraction

### Patterns to KEEP
1. Generate the handoff's evidence.v1 records from receipts by script, so a gate re-run regenerates them without hand edits.
2. A red-first regression test that runs the real verifier for every reviewer-found control defeat, not a stub.
3. Pin refcheck exemptions to file, line and ref, rather than editing approved records.

### Patterns to DROP
1. Stubs that return a bare `(0, "OK")` for a verifier whose output carries the verified values. A stub that drops the payload cannot test the binding.

### Patterns to ADD
1. Whenever a gate passes or fails on a child verifier's exit code, also bind the verifier's structured output to the action that follows.
2. Redirect every red run to a receipt file, even an exploratory one.

### Calibration Adjustment
- Estimated time: one plan loop and one execution pass
- Actual time: about 14 hours wall-clock, 7 plan rounds, 2 execution rounds, 3 full gate runs of about 50 minutes each
- Adjusted estimate for similar MEUs: budget plan-review time for the verification gates themselves whenever a plan adds new gate scripts

---

## Next Session Design Rules

```
RULE-1: A gate that admits on a verifier's exit code must also compare the verifier's printed values with the values it installs.
SOURCE: execution review round 1, F-001 (a same-slug --ac-file installed 999 rounds while limits-check verified the repository plan)
EXAMPLE: run_limits_check(plan) == 0 → install block; now verified_limits(said) == block → install block
```

```
RULE-2: Every new test that imports run_parameters_fixtures joins RUN_PARAMETERS_WINDOWS_ONLY in the same change.
SOURCE: H1-2 run 1 (test_retained_python_tests_collect: 1 collection error in the non-Windows install)
EXAMPLE: test_review_limits_audit.py added → scripts/instantiate.py RUN_PARAMETERS_WINDOWS_ONLY gains it
```

```
RULE-3: Never pre-create a dispatch's -OutputDir/<DispatchId>; put the rolling-review base file in a sibling folder and name it in the prompt.
SOURCE: execution round-2 dispatch refused with "Collision error: Directory ... already exists"
EXAMPLE: review-limits-exec-r2/ (refused) → review-limits-exec-r2-base/ plus a prompt path
```

---

## Next Day Outline

1. The human reviews `C:/Temp/agentic-framework/receipts/commit-draft.txt` and commits; no agent commit or push.
2. Follow-up outside this scope: `validation-review.md`'s `begin` example lacks `--goal-anchor` and `--ac-file`.
3. Follow-up: H1-1's unchecked-row predicate skips ids such as `5c2`.
4. Open design point for the human: add the /2 offer schema and `review_ledger.py` to `REQUIRED_COMPONENTS` (D-17).
5. Time estimate: the commit review is human-gated.

---

## Efficiency Metrics

| Metric | Value |
|--------|-------|
| Total tool calls | 1341 (main session) |
| Time to first green test | row 1 (`test_shipped_file_equals_constants`) |
| Tests added | 163 pytest (58 + 46 + 37 + 22), 6 Pester Describes changed, 20 ledger selftest arms, 12 instantiate selftest arms |
| Codex findings | plan: 12 over 7 rounds; execution: 1 blocking (F-001) then 0 |
| Handoff Score (X/7) | 7/7 |
| Rule Adherence (%) | 90 |
| Prompt→commit time | n/a (draft only; no commit) |
| Compactions (auto/manual) | 14 (14/0) |

### Rules Sampled for Adherence Check

| Rule | Source | Followed? |
|------|--------|-----------|
| Never auto-commit or push | AGENTS.md §Commits | Yes |
| The implementer never authors approved | AGENTS.md §Independent Review | Yes |
| Receipts outside the repository | AGENTS.md §Output and Evidence | Yes |
| Tests first, then implement | AGENTS.md §Testing / TDD | Yes |
| Red output kept as a receipt | AGENTS.md §Output and Evidence | Partly: the F-001 red was transcribed from the console |

---

## Instruction Coverage

```yaml
schema: v1
session:
  id: "2469ffc9-4b7e-4176-9e1c-855085be1702"
  task_class: tdd
  outcome: success
sections:
  - id: authority_and_approval
    cited: true
    influence: 3
  - id: planning_contract
    cited: true
    influence: 3
  - id: testing_tdd_protocol
    cited: true
    influence: 3
  - id: execution_contract
    cited: true
    influence: 3
  - id: independent_review
    cited: true
    influence: 3
  - id: output_and_evidence
    cited: true
    influence: 3
  - id: validation_pipeline
    cited: true
    influence: 2
  - id: artifacts_and_context
    cited: true
    influence: 2
  - id: code_quality
    cited: false
    influence: 1
loaded:
  workflows: [create_plan, plan_critical_review, plan_corrections, execution_session, execution_critical_review, execution_corrections]
  roles: [orchestrator, coder, tester]
  skills: []
  refs: [cli-dispatch/SKILL.md, claude-credits/SKILL.md, REVIEW-TEMPLATE.md, HANDOFF-TEMPLATE.md, REFLECTION-TEMPLATE.md, review-vocabulary.yaml]
decisive_rules:
  - "P0:never-auto-commit"
  - "P0:implementer-never-authors-approved"
  - "P0:receipts-redirect"
  - "P1:tests-first-then-implement"
  - "P1:loosening-only-through-verified-human-typed-offer"
conflicts:
  - "task.md row 5c's verbatim python -c vs pwsh quoting (D-15)"
  - "the plan's rl-stage RECEIPTS_DIR vs the dispatch wrapper's OutputDir check (built a separate dispatch stage)"
  - "validate_closeout_artifacts.py --decision-source reads the approved plan's D-8 text exec-<slug> as a template placeholder; reconciled against the handoff, and the plan ids checked by script"
note: "Most review churn was about the verification gates, not the product code."
slim_candidate: [verbatim-inline-python-in-task-rows]
overthinking_observed: false
review_churn:
  rounds_to_approval: { plan: 7, execution: 2 }
  findings_per_round:
    - { round: 1, critical: 0, high: 1, medium: 0, low: 0 }
    - { round: 2, critical: 0, high: 0, medium: 0, low: 0 }
  churned_findings: 1
  finding_categories: { contract_drift: 3, weak_test: 4, stale_reference: 1, boundary_validation: 1, count_reconciliation: 1, other: 2 }
  verdicts: { changes_required: 6, approved: 3 }
meu_work_classes: []
compactions: { count: 14, auto: 14, manual: 0 }
```
