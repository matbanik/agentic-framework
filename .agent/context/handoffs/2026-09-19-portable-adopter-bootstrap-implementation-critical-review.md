---
date: "2026-09-19"
review_mode: "execution"
target_plan: "P:/agentic-framework/docs/execution/plans/2026-09-19-portable-adopter-bootstrap/implementation-plan.md"
verdict: "approved"
loop_id: "portable-adopter-bootstrap-exec-2026-09-19"
round: 4
findings_count: 4
blocking_findings_count: 0
template_version: "2.1"
requested_verbosity: "standard"
agent: "codex-independent-reviewer"
---

# Critical Review: 2026-09-19-portable-adopter-bootstrap

## Intent Anchor

A naive adopter should install into an empty repository, complete ADOPTION-GUIDE Steps 0–9 through a real plan/task write, and obtain green build preflight without inventing registry snapshots, damaging project files, or guessing template/D6/dispatch paths. HD-03 is unanswered, so an explicit incompleteness receipt is the correct deliverable; the implementation does not yet fully establish the remaining intent.

## Findings

| # | Severity | Blocking | Kind | Finding | File:Line | Recommendation | Status |
|---|---|---|---|---|---|---|---|
| R1 | High | yes | behavior | AC-WP3-2 / AC-12 requires a framework-owned inventory and preservation of user notes. iter_owned_text_files still scans the whole adopter tree, excluding only PROJECT-PROFILE.md and _probe. A normal apply changed user-notes.md from 'Preserve literal {{PROJECT_NAME}}' to 'Preserve literal acme' and exited 0. | scripts/instantiate.py:147-160 | Restrict substitution and verification to an explicit installed framework inventory; add a user-note and application-template preservation fixture outside the two exclusions. | fixed |
| R2 | High | yes | control-defeat | mechanism: unvalidated-replay-status. AC-WP7-1 / AC-31 and IR-1/IR-5 are not proven. The replay writes a three-line plan directly without reading installed templates or following create-plan, and hard-codes D9/egress success. Its checker accepts D6_EXIT=1 and LINT_EXIT=1, returning OK/0. Thus failed adopter validation can pass the claimed end-to-end acceptance gate. | scripts/tests/test_adoption_contract.py:321-348; scripts/tests/run_wp7_replay.py:93-114,143-163 | Exercise the documented install and first-plan procedure using installed templates and observed D9/egress outcomes. Parse and require successful child statuses and verify fixture artifacts; retain a failed-D6/failed-lint negative fixture. | fixed |
| R3 | Medium | no | behavior | AC-WP5-3 / AC-24: H1-1 rejects a completed task because it treats the standard '&#124; `[ ]` &#124; Not started &#124;' status-legend row as unfinished implementation. The exact generated Python check exited 1 with every real task completed. | core/templates/TASK-TEMPLATE.md:85 | Limit the check to actual implementation task rows and test a completed task containing the standard legend. Non-blocking under the workflow's materiality rule for validation-predicate defects. | fixed |
| R4 | Medium | no | behavior | AC-WP4-3 / AC-20 claims a second successful D6 argv proving pytest is optional, but case_d6 only runs pytest twice and a deliberately missing Python module. It never registers or executes a successful alternate D6 command, nor tests a missing executable. | scripts/tests/test_adoption_contract.py:233-271; .agent/context/handoffs/2026-09-19-portable-adopter-bootstrap-handoff.md:58 | Add a successful non-pytest D6 invocation using fixture profile argv and an actual missing-executable case. Correct the evidence description; no demonstrated runtime D6 defect independently blocks this round. | fixed |

All four findings have High confidence. R1/R3 concern the shipped deliverable; R2/R4 concern committable acceptance tooling. R1 and R2 alone determine this verdict. R3 is a non-blocking validation-predicate defect; R4 lacks a demonstrated incorrect runtime D6 outcome and therefore also remains non-blocking.

## Scope

**Review type:** execution, new loop, round 1. The work author is `cursor-grok-4.6`; this independent review is by `codex-independent-reviewer`.

**Targets:** the explicitly named work handoff, implementation plan, task table, AC-WP1-1 through AC-WP7-1 and their AC-1 through AC-31 aliases, claimed tracked diffs, all three new scripts/tests files, current-focus/INSTANTIATE seeds, and both plan-local checks. The plan names one work handoff and `meus: []`; no multi-MEU expansion applies.

**Evidence:** current source/diffs and the named receipts under `C:/Temp/agentic-framework/receipts/`. The original WP7 fixture was read at `C:/Temp/agentic-framework/wp7-adopt-2026-09-19`. Its installed templates exist, but its actual plan contains only a title and the two D9/egress statements; `docs/BUILD_PLAN.md` is absent. This confirms the replay script's limited scope.

**Boundaries:** the approved human plan-to-execution gate, HD-03 incompleteness route, and empty MEU list were accepted. No trust-boundary challenge was raised. No providers were invoked, no origin instantiation was performed, and neither `P:/.agent` nor `P:/fw-adopt-probe` was copied or mutated. This review writes only this file inside the repository; temporary probes and JSON receipts are outside it.

## Checklist Results

Exit columns distinguish commands that read evidence from tested child processes. A receipt-reader exit 0 means the evidence was read; it does not turn a recorded child failure into a pass.

### Implementation Review (IR)

| Check | Result | Command | Exit | Evidence |
|---|---|---|---|---|
| IR-1 / IR-5: adopter replay and negative-path rigor | fail | `rtk proxy python -X utf8 -c "from pathlib import Path; print(Path('C:/Temp/agentic-framework/receipts/exec-r1-targeted.json').read_text()); print(Path('C:/Temp/agentic-framework/receipts/exec-r1-contract.json').read_text())"` | 0 | Read saved targeted results: failed D6 and lint statuses were accepted by --case wp7 (child exit 0). Source audit also shows direct minimal-plan writes bypassing installed templates. R2. |
| IR-6: installer ownership boundary | fail | `rtk proxy python -X utf8 -c "from pathlib import Path; print(Path('C:/Temp/agentic-framework/receipts/exec-r1-targeted.json').read_text()); print(Path('C:/Temp/agentic-framework/receipts/exec-r1-contract.json').read_text())"` | 0 | Installer child exited 0 after rewriting user-notes.md. exec-r1-targeted.json records the temporary fixture and changed value. R1. |
| IR-7: all 31 closeout AC aliases represented | pass | `rtk proxy python -B core/tools/validate_closeout_artifacts.py --plan docs/execution/plans/2026-09-19-portable-adopter-bootstrap/implementation-plan.md --handoff .agent/context/handoffs/2026-09-19-portable-adopter-bootstrap-handoff.md --ac-coverage-only` | 0 | All 31 plan aliases present. This checks representation, not fulfillment; AC-12 and AC-31 remain blocked. |
| IR-2 / IR-3: API stubs and HTTP error mapping | n/a | — | — | No API routes or persistence stubs in this adoption-framework change. |
| IR-4: prior execution corrections | n/a | — | — | New execution loop, round 1; closed plan-review decisions were not reconsidered. |

IR-5's case-by-case assertion audit is below. IR-6 also reviewed the preflight's refusal/usage/fail-closed arms, locator no-fallthrough behavior, encoding negative oracle, installer collision guard, and linter scriptblock refusal. No runtime/API schema requirement was invented for prose-only workflow surfaces.

### Documentation Review (DR)

| Check | Result | Command | Exit | Evidence |
|---|---|---|---|---|
| DR-1 / DR-4: H1-1 behavior and D6 claim accuracy | partial | `rtk proxy python -X utf8 -c "from pathlib import Path; print(Path('C:/Temp/agentic-framework/receipts/exec-r1-targeted.json').read_text()); print(Path('C:/Temp/agentic-framework/receipts/exec-r1-contract.json').read_text())"` | 0 | H1 completed-task check exited 1 solely because of the status legend. Source-read of case_d6 confirms no successful alternate argv. R3/R4 are non-blocking. |
| DR-5 / DR-8: preflight and HD-03 receipt evidence | pass | `rtk proxy python -X utf8 -c "from pathlib import Path; names='preflight-selftest hd03-live-registry wp7-adopter-replay'.split(); [(print(n),print((Path('C:/Temp/agentic-framework/receipts')/(n+'.txt')).read_text(encoding='utf-8-sig'))) for n in names]"` | 0 | Receipt read below; preflight reports 30 arms/0 failures, HD-03 starts INCOMPLETE and names forwarding wrappers. WP7 child exits are zero in the authoritative receipt, but its claimed integration scope is overstated. |

DR-2/DR-3/DR-6: inspected changed TEMPLATE_HOME, D6, D9 and EGRESS_PRECEDENCE consumers against their installed destinations and actual source. The review does not claim a repository-wide absence of every legacy token or every unshipped dependency. DR-7 uses the supplied selftest totals (30 preflight, 30 installer, 50 linter); no full suite was re-run to reproduce those totals. DR-8 accepts INCOMPLETE as the explicitly approved HD-03 branch, while rejecting the broader completion claims in R1/R2.

### Post-Implementation Review (PR)

| Check | Result | Command | Exit | Evidence |
|---|---|---|---|---|
| PR: handoff structure and plan binding | pass | `rtk proxy python -B core/tools/validate_closeout_artifacts.py --handoff .agent/context/handoffs/2026-09-19-portable-adopter-bootstrap-handoff.md --plan docs/execution/plans/2026-09-19-portable-adopter-bootstrap/implementation-plan.md` | 0 | Required sections and 31 AC rows verified. Targeted rerun because receipt had no separate exit metadata. |
| PR: packaged MEU seed | pass | `rtk proxy python -B -X utf8 -c "import pathlib,sys; t=pathlib.Path('core/.agent/context/meu-status.yaml').read_text(encoding='utf-8'); sys.exit(0 if 'meus: []' in t else 1)"` | 0 | Targeted rerun of empty meu-noop.txt receipt; packaged empty MEU list remains. |
| PR: OpenAPI skip basis | pass | `rtk proxy python -B -X utf8 -c "import pathlib,sys; sys.exit(0 if not pathlib.Path('packages/api').exists() else 1)"` | 0 | Targeted rerun of empty openapi-skip.txt receipt; packages/api is absent. |

FAIL_TO_PASS and Commands Executed tables exist in the handoff. Their red descriptions are prose, not independent preserved red-run transcripts; they were not used as runtime proof. H2 reflection/metrics are post-review work, not missing prerequisites for this round.

### Authoritative Receipt Inventory

These receipts were read in this review. Where the file does not embed an overall exit, the exit below is explicitly the paired handoff command-table claim, not a new reviewer run. Blank no-op receipts and unpaired handoff-validation exits received the targeted reruns above.

| Receipt | Exact underlying command / producer | Exit evidence | What it establishes |
|---|---|---|---|
| wp1-guide.txt | `python scripts/tests/test_adoption_contract.py --case wp1` | paired handoff: 0 | Named locator negative case and text guards pass; not every locator scenario. |
| preflight-selftest.txt | `bash core/tools/preflight.sh --selftest` with Git usr/bin prepended | paired handoff: 0; 30 child statuses printed | 30 arms, 0 failures; first-line classes and build registry skip. |
| wp2-encoding.txt | `python scripts/tests/test_ps1_encoding.py` | paired handoff: 0 | Five core ps1 files pass ASCII/BOM and available-shell parser checks. |
| wp3-templates.txt | `python docs/execution/plans/2026-09-19-portable-adopter-bootstrap/checks/assert_wp3.py` | paired handoff: 0 | Text checks for TEMPLATE_HOME and D9 pass. |
| instantiate-selftest.txt | `python scripts/instantiate.py --selftest` | paired handoff: 0; 30 arms pass | Missing-root, PROFILE/_probe preservation, rename and collision arms; user-note omission is R1. |
| wp4-mcp.txt | `python scripts/tests/test_adoption_contract.py --case d6` | paired handoff: 0 | Toy pytest and diagnostic retention; alternate-D6 omission is R4. |
| lint-selftest.txt | `python core/tools/lint_task_contract.py --selftest` | paired handoff: 0; 50 arms print expected/actual exits | Positive rows and scriptblock/pipe/exit/dependency refusals. |
| wp6-profile.txt | `python scripts/tests/test_adoption_contract.py --case profile-permissions` | paired handoff: 0 | Profile slot and workflow text checks. |
| hd03-live-registry.txt | WP1B written incompleteness artifact; `python scripts/tests/test_adoption_contract.py --case hd03` | paired handoff checker: 0 | Starts INCOMPLETE; names both forwarding wrappers; no compile/sync/enforce claim. |
| wp7-adopter-replay.txt | `scripts/tests/run_wp7_replay.py`; `python scripts/tests/test_adoption_contract.py --case wp7` | child instantiate/D6/lint/preflight: 0; paired checker: 0 | Real limited fixture operations; does not prove Steps 0–9 integration (R2). |
| lint-task.txt | `python core/tools/lint_task_contract.py --task docs/execution/plans/2026-09-19-portable-adopter-bootstrap/task.md` | output: 29 rows, 25 checked, 4 view-file exemptions; overall exit not embedded | Structural result only; not treated as proof of task completion. |
| meu-noop.txt | Exact rerun in PR table | reviewer: 0 | Empty seed retained. |
| openapi-skip.txt | Exact rerun in PR table | reviewer: 0 | API tree absent. |
| handoff-check.txt | Exact rerun in PR table | reviewer: 0 | Sections and plan binding. |
| handoff-ac-check.txt | Exact rerun in IR table | reviewer: 0 | All 31 aliases represented. |
| build-plan-hub.txt | `Test-Path docs/BUILD_PLAN.md` | paired handoff: 0; content False | Origin hub absence, not adopter replay completeness. |

## Targeted Reproductions

Targeted probes were needed because the supplied evidence did not exercise the claimed ownership boundary and because the replay's success claim contradicted its source. No full suites were repeated.

### R1 — user-note preservation

Fixture: `C:/Temp/agentic-framework/exec-r1-drq133v3/owned`. Input files were `AGENTS.md` containing the project-name token and `user-notes.md` containing `Preserve literal {{PROJECT_NAME}}`.

Actual child argv (Python executable resolved by the parent):

```text
python -B scripts/instantiate.py --root C:/Temp/agentic-framework/exec-r1-drq133v3/owned --project-name acme --project-root C:/Temp/agentic-framework/exec-r1-drq133v3/owned --receipts-dir C:/Temp/agentic-framework/exec-r1-drq133v3 --repo-url example.invalid/acme
```

Child exit **0**; installer reported both files changed; the user note became `Preserve literal acme`. Saved result: `C:/Temp/agentic-framework/receipts/exec-r1-targeted.json`. This is ordinary user-authored content, not an adversarial path or a request to widen the trust boundary.

The same probe extracted the actual Step 2 PowerShell block, substituted only package/destination paths, and ran it through `powershell -NoProfile -NonInteractive -Command` in a new path containing spaces. It exited **0**, and both agent-def directories were populated. The suspected empty-destination copy failure was dropped.

### R2 — failed replay accepted

With `RECEIPTS_DIR=C:/Temp/agentic-framework/exec-r1-contract-2yppaxqf/receipts`, the exact checker invocation was `python -B scripts/tests/test_adoption_contract.py --case wp7`.

Input `wp7-adopter-replay.txt`:

```text
fixture=C:/Temp/agentic-framework/exec-r1-contract-2yppaxqf
D6_EXIT=1
LINT_EXIT=1
PREFLIGHT_FIRST=OK: build prerequisites passed
PREFLIGHT_EXIT=0
PROVIDER_CALLS=0
D9_NO_BRANCH=yes
```

Actual result: **exit 0**, `OK: wp7 disposable adopter replay`. This explicitly represents a failing adopter validation and lint result; neither is checked. The gate also did not require actual first-plan artifacts. The authoritative green receipt is not alleged to contain failed statuses: the finding is that its claimed acceptance mechanism cannot reject them, and its producer bypasses the documented first-plan procedure.

Saved input/result: `C:/Temp/agentic-framework/receipts/exec-r1-contract.json`.

### R3 — completed task refused

A copy of the real task was placed at `C:/Temp/agentic-framework/exec-r1-contract-2yppaxqf/docs/execution/plans/2026-09-19-done/task.md`, with every H1/H2 row marked complete and all already-complete implementation rows preserved. The shipped H1-1 Python command, with only the plan-folder placeholder filled, was executed through PowerShell in that fixture.

Actual exit: **1**. The only matched line was the standard status-legend entry `[ ] / Not started`. The exact Python command and exit are retained in `exec-r1-contract.json`. This fail-closed predicate defect is recorded non-blocking under the review materiality rule.

## IR-5 Assertion Audit

| File / case | Grade | Assessment |
|---|---|---|
| test_adoption_contract.py: wp1 | Adequate | Real missing-home refusal for Python resolver and PowerShell module; text guards for other contracts. Does not exercise check_model_slugs or empty-catalog schema validation. |
| templates-installed | Adequate | Named consumer presence/absence checks and focus-file existence; weaker than installed-template use. |
| d9-no | Weak (Medium, non-blocking) | Presence/proximity checks can accept unconditional MEU instructions elsewhere; no D9=yes missing-assets execution. Covered by R2's missing integrated first-plan proof, not a separately escalated blocker. |
| d6 | Weak (Medium, non-blocking) | Positive/failing pytest subprocesses and both diagnostic strings are real; registered alternate argv and missing executable are absent (R4). |
| profile-permissions | Adequate for text, weak for integration | Confirms slots and permission wording only. Does not observe an agent's forbidden-egress action; R2's hard-coded replay flags do not supply that missing proof. |
| hd03 | Adequate for selected INCOMPLETE branch | Requires first-line class and wrapper names. READY provenance is only a string check; that conditional branch was not selected or approved here. |
| wp7 | Weak (High, blocking) | Concrete failed-status false-pass (R2). |
| run_wp7_replay.py | Weak (High, blocking) | Real copy/instantiate/pytest/lint/preflight children, but no template-based create-plan execution; D9/egress results are constants (R2). |
| test_ps1_encoding.py | Strong byte oracle; Adequate parser checks | BOM-less em-dash refusal, ParseFile diagnostics, and missing-prompt behavior are checked. Missing one of the two shells silently skips that shell, so the summary alone does not identify both versions. |
| instantiate.py selftest | Strong argument guards; Adequate ownership/rename arms | Specific exits, preserved PROFILE/_probe content and collision error are asserted. Only one rename is explicitly inspected; arbitrary user notes are omitted (R1). |
| preflight.sh selftest | Strong | Positive controls plus explicit 0/1/2/3 child exits, matching first-line classes, and no-fallthrough fixture. |
| lint_task_contract.py selftest | Strong | 50 expected/actual exit-prefix arms; new scriptblock refusal requires the diagnostic. No test runs the H1-1 semantic predicate (R3). |
| checks/assert_wp3.py | Adequate | Propagates first nonzero child; inherits the child checks' limits. |
| checks/assert_exec_review_approved.py | Adequate | Two-stage receipt production/consumption with both child exits propagated; not run to approve this review. |
| Test-CliDispatch.ps1 | Mixed, unchanged semantics | Wrapper contract/validation arms assert refusals and output; agy/creative-writing smoke checks are Adequate; image arm is Weak because text or pre-existing images can satisfy it. Encoding/message edits only for this work; no live dispatch evidence claimed. |
| Test-OpenCodePoC.ps1 | Mixed, unchanged semantics | Install/auth/JSON checks are Adequate probes; hello, Bedrock Claude/GPT, directory, permissions and validation success fallbacks are Weak (Medium observations) because content length/presence can substitute for requested behavior. Only encoding/comment changes are in scope; live dispatch is excluded. |

The Weak ratings above are not approvals of those tests as behavioral evidence. Legacy live-provider probes are outside this deferred-adoption acceptance path and do not create additional blocking findings.

## Verdict

**changes_required** — R1 violates explicit user-content preservation, and R2 leaves the central disposable-adopter acceptance claim unproven while accepting failed validation statuses. Fix those through the separately authorized corrections workflow, retain the negative fixtures, and obtain the next independent execution review. R3/R4 remain actionable but do not independently gate approval.

HD-03 INCOMPLETE is accepted. No working compiler, live registry readiness, or paid provider dispatch is required or claimed by this verdict.

**Residual limits:** source-level permission guards were inspected, not exercised through a paid external provider; original authoritative selftest receipts were reused; no claim is made that the first-plan path is complete. No changes beyond this rolling review were made inside the repository.

**Timestamp:** omitted as requested because `.agent/skills/timestamp/scripts/stamp.py` does not exist in the origin workspace. The packaged copy exists under `core/`; it was not installed in place or substituted for the requested path.


## Recheck (2026-09-19)

**Workflow:** `/execution-critical-review` round 2  
**Agent:** `codex-independent-reviewer` (independent of producer `cursor-grok-4.6`)  
**Loop:** `portable-adopter-bootstrap-exec-2026-09-19`  
**Review mode:** `execution`; **requested verbosity:** `standard`

### Intent Anchor

The execution should let a naive adopter install into an empty repository, follow ADOPTION-GUIDE Steps 0–9 through a real first-plan/task write, and pass build preflight while preserving adopter content. The preservation defect is fixed; the original integrated first-plan proof remains incomplete.

### Prior Pass Summary

| Finding | Prior Status | Recheck Result |
|---|---|---|
| R1 — installer rewrites user notes | Open, High, blocking | **Fixed.** Installed-path allowlist and both new preservation arms confirmed. |
| R2 — false WP7 acceptance / missing first-plan integration | Open, High, blocking | **Partially fixed; still open.** Failed D6/lint statuses now refuse. Original first-plan workflow bypass remains. |
| R3 — H1-1 matches the status legend | Open, Medium, non-blocking | **Fixed.** Actual command passes completed tasks plus legend and rejects an unchecked numeric task. |
| R4 — alternate D6 / missing executable not exercised | Open, Medium, non-blocking | **Fixed.** Both arms now exist; targeted D6 case exits 0. |

### Remaining Findings

| # | Severity | Blocking | Kind | Finding | File:Line | Recommendation | Status |
|---|---|---|---|---|---|---|---|
| R2 | High | yes | control-defeat | mechanism: unvalidated-replay-status. AC-WP7-1 / AC-31 and IR-1/IR-5 still lack the required first-plan integration. Installed templates are read only for marker checks, followed by hard-coded plan/task writes and unconditional template-used flags. The live plan contains only a Goal section, with no acceptance criteria or verification plan, while the checker returns OK/0. | scripts/tests/run_wp7_replay.py:100-170,214-215; core/.agent/workflows/create-plan.md:178-185 | Finish the original correction: exercise the installed first-plan procedure using template structures and PROFILE decisions; validate the resulting plan/task before claiming integrated acceptance. Preserve the repaired failed-status checks. | open |

**Confidence:** High. **Subject:** committable-tooling. This carries forward R2 and its original mechanism; no new finding ID, deeper mutation, or expanded trust boundary is introduced. The blocker is the missing integration and false completion claim, not a cosmetic template-section discrepancy. The original round-1 finding expressly required a real installed-template/create-plan path.

### Confirmed Fixes

- **R1 / AC-WP3-2 / AC-12:** `scripts/instantiate.py:181-201` gates traversal through the installed inventory defined at lines 98–112. The preservation assertions at lines 553–565 check user notes/application templates and framework substitution. `instantiate-selftest.txt` reports **32 arms, 0 failures**, including both new arms. The existing complete receipt and source were inspected; the installer suite was not repeated. No additional ownership mutation class was pursued.
- **R2, repaired portion:** `scripts/tests/test_adoption_contract.py:361-374` requires successful child statuses and expected D9/egress values; lines 381–396 retain a failed-status negative fixture. Separate reviewer probes of the actual parser returned `D6_EXIT is '1', want 0` and `LINT_EXIT is '1', want 0`. The original failed-child false-pass is closed. PROFILE-derived D9/C1 variables now exist at `run_wp7_replay.py:91-96,113-122,200-212`; this is credited without claiming that those string branches execute create-plan.
- **R3 / AC-WP5-3 / AC-24:** `core/templates/TASK-TEMPLATE.md:85` restricts the first cell to numeric task IDs. Executing its extracted Python code in an isolated temporary fixture returned **0** for a completed numeric task with the status legend and **1** after marking that task unchecked.
- **R4 / AC-WP4-3 / AC-20:** `scripts/tests/test_adoption_contract.py:264-284` invokes a nonexistent executable, handles `FileNotFoundError`, and requires exit 0 plus `alt-d6-ok` from the alternate non-pytest argv. The targeted D6 case returned **0** and still checks both failure diagnostics.

### Scope and Evidence

Rechecked R1–R4 against the correlated work handoff's Corrections Applied section, plan ACs, task table, current implementation, and the five requested receipts. This remains the same single-handoff, non-product `meus: []` project. Unchanged round-1 checks were not reopened. The installed fixture was inspected read-only at `C:/Temp/agentic-framework/wp7-adopt-2026-09-19`; no provider was called.

All requested receipts were read: `instantiate-selftest.txt`, `wp4-mcp.txt`, `wp7-adopter-replay.txt`, `wp7-exists.txt`, and `wp5-template-lint.txt`. The WP7 receipt records instantiate/D6/lint/preflight exits 0; these real subprocess successes are credited. The template-lint receipt reports 15 rows, 10 fully checked, 3 placeholder exemptions, and 2 view-file exemptions; it is structural evidence, not proof of H1 semantics or first-plan integration.

**Concrete remaining R2 evidence:** `C:/Temp/agentic-framework/wp7-adopt-2026-09-19/docs/execution/plans/2026-09-19-wp7-first/implementation-plan.md` is 16 lines, with only its title and `## Goal` headings. The generated task has one hard-coded pytest row. Reading templates at replay lines 100–109 does not feed their contents into the writes at lines 123–170. Installed create-plan lines 178–185 require using the template structures as the skeleton. Nevertheless, the receipt reports both `*_FROM_TEMPLATE=yes` and `--case wp7` returns 0. This confirms the original bypass without introducing a new attack fixture.

### Checklist Results

Reader exits below are separated from tested child outcomes. A reader returning 0 does not mean the inspected integration passed.

| Check | Result | Command | Exit | Evidence |
|---|---|---|---|---|
| IR-6 / R1 ownership preservation | pass | C1 below | 0 (reader) | 32-arm installer receipt; named preservation arms pass; current allowlist and assertions inspected. |
| IR-5 / R2 failed-status regression | pass | C1 below | 0 (reader) | Separate actual-parser probes reject D6_EXIT=1 and LINT_EXIT=1; original status defect closed. |
| IR-1 / IR-7 / DR-1 / R2 integration claim | fail | C1 below; C3 below | 0 | Live fixture is still a minimal hard-coded substitute for the required first-plan workflow; WP7 checker nevertheless exits 0. |
| IR-4 / R3 semantic regression | pass | C1 below | 0 (reader) | Extracted template command: completed-with-legend exit 0; unchecked numeric task exit 1. |
| IR-5 / R4 D6 negative and alternate paths | pass | C2 below | 0 | Non-pytest argv, missing executable, and two retained failure diagnostics are exercised. |
| IR-2 / IR-3 API persistence/error mapping | n/a | — | — | No API or persistence surfaces in these corrections. |

Commands and reproducible evidence:

- **C1:** `rtk proxy python -B -X utf8 -c "from pathlib import Path; print(Path('C:/Temp/agentic-framework/receipts/exec-r2-targeted.json').read_text(encoding='utf-8')); print(Path('C:/Temp/agentic-framework/receipts/instantiate-selftest.txt').read_text(encoding='utf-8-sig'))"`
- **C2:** `C:/Python314/python.exe -B scripts/tests/test_adoption_contract.py --case d6` — child exit 0.
- **C3:** `C:/Python314/python.exe -B scripts/tests/test_adoption_contract.py --case wp7` with `RECEIPTS_DIR=C:/Temp/agentic-framework/receipts` — child exit 0.
- The reviewer also read the full replay/parser source and the live generated plan/task using `rtk proxy python -B -X utf8 -c`. Targeted in-process parser probes and the two H1 subprocess outcomes, including the exact extracted command, are retained in `C:/Temp/agentic-framework/receipts/exec-r2-targeted.json`. D6 and WP7 checker commands were rerun narrowly to attach current explicit exits to terse receipts; the full replay and full suites were not rerun.
- **IR-5 delta audit:** new installer ownership assertions are Strong for the reported defect; R3's positive/negative command probe is Strong; D6's new argv/missing-executable arms are Strong for their subprocess outcomes; WP7 child-status checks are Strong for the original status defect, but the replay remains Weak for claimed first-plan integration. Unchanged case grades remain in round 1.

### Verdict

`changes_required` — **one remaining High blocking finding, R2**. R1, R3, and R4 are fixed. Finish R2 through a separately authorized corrections phase; this reviewer makes no implementation changes. No new findings or out-of-contract blockers were added.

```yaml
schema_version: review-verdict.v2
date: "2026-09-19"
review_mode: execution
loop_id: portable-adopter-bootstrap-exec-2026-09-19
round: 2
agent: codex-independent-reviewer
verdict: changes_required
findings_count: 1
blocking_findings_count: 1
fixed_findings: [R1, R3, R4]
open_findings: [R2]
```

Round 1 is preserved verbatim above. Only this canonical rolling review file was edited inside the repository; no product, test, plan, task, or work-handoff file was edited, and no commit was made. The workflow's review-only hard stop controls this turn; pending implementer closeout tasks are not authorization for reviewer execution.

🕐 Completed: 2026-09-19 23:56 (EDT)

## Recheck (2026-09-20)

**Workflow:** `/execution-critical-review` round 3  
**Agent:** `codex-independent-reviewer`, independent of producer `cursor-grok-4.6`  
**Loop:** `portable-adopter-bootstrap-exec-2026-09-19`  
**Review mode:** `execution`; **requested verbosity:** `standard`

### Intent Anchor

The execution should let a naive adopter install into an empty repository, write the first plan/task using installed templates and PROFILE decisions, and pass build preflight with the registry deferred. This recheck confirms the remaining R2 correction for that bootstrap path; it does not claim a completed external plan review or an execution-ready fixture plan.

### Prior Pass Summary

| Finding | Prior Status | Recheck Result |
|---|---|---|
| R1 — installer rewrites user notes | Fixed in round 2 | Remains closed; no deeper ownership mutation pursued. |
| R2 — false WP7 acceptance / missing installed first-plan skeleton | Partially fixed, High, blocking | **Fixed.** Installed template contents now feed the writes; real fixture files are inspected, and the original Goal-only failure refuses. |
| R3 — H1-1 matches the status legend | Fixed in round 2 | Remains closed; no new variant pursued. |
| R4 — alternate D6 / missing executable | Fixed in round 2 | Remains closed; no new variant pursued. |

### Remaining Findings

| # | Severity | Blocking | Kind | Finding | File:Line | Recommendation | Status |
|---|---|---|---|---|---|---|---|
| R5 | Low | no | clerical | The fixture retains example AC/spec/verification/MEU placeholders; it demonstrates installed-template skeleton generation, not an execution-ready project plan. | scripts/tests/run_wp7_replay.py:123-164 | Keep the receipt scoped to bootstrap smoke coverage; fill project-specific content before real execution. | accepted_risk |

R5 has **High confidence**, subject **committable-tooling**. It records the residual template limitation once under the functionality-first and nearby-mutation rules. It is not a new blocker or a reason to consume another review round. R2's original `unvalidated-replay-status` mechanism is closed, not renamed or escalated.

### Confirmed Fixes

- **R2 / AC-WP7-1 / AC-31:** `run_wp7_replay.py:100-103,123-143` reads the installed PLAN-TEMPLATE and uses its contents as the generated plan skeleton. The installed TASK-TEMPLATE head feeds the task write at lines 144-164. A reviewer assertion evaluated only those existing pure transformations and proved exact text equality with both live fixture artifacts.
- **PROFILE application:** lines 91-96 and 113-122 derive the D9 and egress sentences. The live PROFILE's D9=no and C1=forbid values agree with the filled Goal. The producer receipt records zero provider calls and the named-human stop. No paid/provider run is claimed.
- **Artifact validation:** `test_adoption_contract.py:374-393` reads the actual fixture plan/task and requires the reported sections and template markers. The original Goal-only plan now produces explicit missing-section errors; separately removing Acceptance Criteria, Verification Plan, or Spec Sufficiency produces the matching diagnostic. A minimal task is rejected.
- **Failed-status repair retained:** lines 361-373 continue requiring successful child statuses. Separate probes on the valid live receipt returned exactly `D6_EXIT is '1', want 0` and `LINT_EXIT is '1', want 0`. Positive live and copied fixture inputs returned no errors.

### Scope and Evidence

Correlated the single project work handoff (`2026-09-19-portable-adopter-bootstrap-handoff.md`, Corrections Applied R2), the plan's AC-WP7-1 / AC-31, task row 15, the two WP7 source files, and the supplied fixture/receipts. This remains a non-product `meus: []` project. Earlier-round checks and findings are retained above rather than reopened.

Read `wp7-adopter-replay.txt` and `wp7-exists.txt`. The replay receipt explicitly records instantiate, D6, lint, and build-preflight exits **0**, with one fully checked task row. Those subprocess receipts were reused; neither the destructive full replay nor the full suites were repeated. The terse `wp7-exists.txt` has no embedded exit, so the reviewer reran only `--case wp7`, obtaining exit **0**.

The source files are untracked within the pre-existing dirty workspace; the scoped `git diff` therefore supplied no source delta. Direct file reads and source-to-live-artifact comparisons establish current state. Baseline hashes were captured before the sole repository edit.

### Checklist Results

Reader status is distinguished from tested outcomes below.

| Check | Result | Command | Exit | Evidence |
|---|---|---|---|---|
| IR-1 / IR-7 — WP7 acceptance | pass | C1 | 0 (child) | Current checker accepts live fixture; authoritative replay child statuses are 0. |
| IR-4 / IR-5 / IR-6 — original R2 negative paths | pass | C2 | 0 (reader; assertion harness also 0) | Failed D6/lint, original Goal-only plan, individual absent sections, and minimal task all reject; positive controls pass. |
| DR-1 / DR-4 / DR-5 — claim and template binding | pass | C2 | 0 (reader; assertion command also 0) | Generated files exactly equal installed-template transformations; PROFILE decisions match. |
| IR-2 / IR-3 — API/persistence | n/a | — | — | No such surfaces changed in this recheck. |

- **C1:** `C:/Python314/python.exe -B scripts/tests/test_adoption_contract.py --case wp7`, with `RECEIPTS_DIR=C:/Temp/agentic-framework/receipts`.
- **C2:** `rtk proxy python -B -X utf8 -c "from pathlib import Path; print(Path('C:/Temp/agentic-framework/receipts/exec-r3-targeted.json').read_text(encoding='utf-8-sig')); print(Path('C:/Temp/agentic-framework/receipts/exec-r3-template-binding.txt').read_text(encoding='utf-8-sig'))"`
- **Targeted receipt:** `C:/Temp/agentic-framework/receipts/exec-r3-targeted.json` contains the raw RTK receipt with the JSON result payload, exact child argv/exit, positive and negative parser results, and temporary fixture path. It is a raw receipt, not a standalone JSON document.
- **Template-binding receipt:** `C:/Temp/agentic-framework/receipts/exec-r3-template-binding.txt` records successful assertions comparing both actual generated files with the replay's pure template transformations and checking the PROFILE decisions and original replay statuses.
- Negative probes used a new temporary fixture under the receipts directory; the supplied live fixture was unchanged.
- Reviewer environment preflight: `core/tools/preflight.sh --phase build`, exit **0**, five checks passed. Receipt: `exec-r3-preflight.txt`. The origin package is deliberately uninstantiated; its absent root PROFILE was not treated as an instruction to adopt or rewrite the origin.
- **IR-5 delta grades:** replay is **Adequate** for this installed-template bootstrap smoke; current section/status checks are **Adequate**, and the reviewer positive/negative regression assertions are **Strong** for the reported failure. Unchanged test cases retain their prior-round grades.

### Verdict

**approved** — R2's remaining installed-template bypass is fixed; R1, R3, and R4 remain closed. No blocking findings survive. R5 is a non-blocking, accepted fixture limitation.

HD-03 remains the accepted INCOMPLETE branch. This verdict does not assert live registry readiness, paid external review, or readiness to execute the placeholder-bearing fixture plan. No additional correction/recheck is required for the recorded residual limitation. Implementer closeout remains outside this review turn.

### Structured Verdict

```json
{
  "schema_version": "review-verdict.v2",
  "date": "2026-09-20",
  "review_mode": "execution",
  "loop_id": "portable-adopter-bootstrap-exec-2026-09-19",
  "round": 3,
  "target_plan": "docs/execution/plans/2026-09-19-portable-adopter-bootstrap/implementation-plan.md",
  "agent": "codex-independent-reviewer",
  "requested_verbosity": "standard",
  "verdict": "approved",
  "summary": "R2 is fixed; R1, R3, and R4 remain closed. Round 3 appended to .agent/context/handoffs/2026-09-19-portable-adopter-bootstrap-implementation-critical-review.md, preserving rounds 1–2. One non-blocking fixture limitation remains. No product/test/plan/task/work-handoff edits or commit.",
  "findings": [
    {
      "id": "R5",
      "severity": "Low",
      "confidence": "High",
      "blocking": false,
      "subject": "committable-tooling",
      "finding_kind": "clerical",
      "finding": "The generated fixture retains example AC, spec-sufficiency, verification-command, and MEU placeholders. It proves installed-template skeleton generation, not an execution-ready project plan.",
      "file_line": "scripts/tests/run_wp7_replay.py:123-164",
      "recommendation": "Keep the receipt scoped to bootstrap smoke coverage; fill project-specific content before using such a plan for real execution. No additional review round is required for this residual limitation.",
      "status": "accepted_risk"
    }
  ],
  "checklist_results": [
    {
      "check": "IR-1 / IR-7: WP7 acceptance recheck",
      "result": "pass",
      "command": "C:/Python314/python.exe -B scripts/tests/test_adoption_contract.py --case wp7",
      "exit_code": 0,
      "evidence": "Executed with RECEIPTS_DIR=C:/Temp/agentic-framework/receipts. Returned OK: wp7 disposable adopter replay. Child invocation and exit are retained in exec-r3-targeted.json; original replay records instantiate/D6/lint/preflight exits 0."
    },
    {
      "check": "IR-4 / IR-5 / IR-6: R2 negative-path evidence",
      "result": "pass",
      "command": "rtk proxy python -B -X utf8 -c \"from pathlib import Path; print(Path('C:/Temp/agentic-framework/receipts/exec-r3-targeted.json').read_text(encoding='utf-8-sig')); print(Path('C:/Temp/agentic-framework/receipts/exec-r3-template-binding.txt').read_text(encoding='utf-8-sig'))\"",
      "exit_code": 0,
      "evidence": "Reader exit 0; underlying targeted assertion harness also exited 0. Actual parser rejects D6_EXIT=1, LINT_EXIT=1, the original Goal-only plan, each missing required section, and a minimal task. Positive copies pass. Live fixture unchanged."
    },
    {
      "check": "DR-1 / DR-4 / DR-5: installed-template binding",
      "result": "pass",
      "command": "rtk proxy python -B -X utf8 -c \"from pathlib import Path; print(Path('C:/Temp/agentic-framework/receipts/exec-r3-targeted.json').read_text(encoding='utf-8-sig')); print(Path('C:/Temp/agentic-framework/receipts/exec-r3-template-binding.txt').read_text(encoding='utf-8-sig'))\"",
      "exit_code": 0,
      "evidence": "Reader exit 0; underlying template-binding assertion command exited 0. Live plan/task equal the replay's transformations of installed templates. PROFILE D9=no and C1=forbid match the filled Goal. Replay graded Adequate for bootstrap smoke; targeted regression assertions Strong."
    },
    {
      "check": "IR-2 / IR-3: API and persistence behavior",
      "result": "n/a",
      "evidence": "No API or persistence changes in this recheck."
    }
  ]
}
```

Rounds 1–2 are preserved byte-for-byte above. The only repository edit in this turn is this append to the canonical rolling review. No product, test, plan, task, or work-handoff file was edited; no commit was made.

🕐 Completed: 2026-09-20 00:04 (EDT)


## Recheck (2026-09-20)

**Workflow:** `/execution-critical-review` round 4  
**Agent:** `codex-independent-reviewer`, independent of producer `cursor-grok-4.6`  
**Loop:** `portable-adopter-bootstrap-exec-2026-09-19`

### Scope and Disposition

This round synchronizes the rolling approval state with the approval already issued in round 3. R1-R5 were not reopened on the merits. R1-R4 remain fixed; R5 remains non-blocking `accepted_risk` as recorded in round 3.

The frontmatter now records `verdict: approved`, `round: 4`, and `blocking_findings_count: 0`. The first Findings table now marks R1-R4 `fixed`; their original descriptions and Blocking classifications remain historical. R5 remains in round 3's Remaining Findings table with Blocking `no` and Status `accepted_risk`. Earlier Recheck sections are unchanged. Statements above about preserving round 1 describe those earlier turns; this round intentionally updates its rolling fields.

### Verification

The closeout validator's native state and approval functions accept the updated file at round 4 with zero open blocking findings. The command below performs both checks in memory, without creating or refreshing a persisted review-state receipt. The structured verdict validates against `core/.agent/schemas/review-verdict.schema.v2.json`.

### Structured Verdict

```json
{
  "schema_version": "review-verdict.v2",
  "date": "2026-09-20",
  "review_mode": "execution",
  "loop_id": "portable-adopter-bootstrap-exec-2026-09-19",
  "round": 4,
  "target_plan": "docs/execution/plans/2026-09-19-portable-adopter-bootstrap/implementation-plan.md",
  "agent": "codex-independent-reviewer",
  "requested_verbosity": "standard",
  "verdict": "approved",
  "summary": "Synchronized the rolling review frontmatter and first Findings table with round 3 approval. R1-R4 remain fixed; R5 remains non-blocking accepted_risk. No findings reopened; only the reviewer-owned file edited; no commit.",
  "findings": [
    {
      "id": "R5",
      "severity": "Low",
      "confidence": "High",
      "blocking": false,
      "subject": "committable-tooling",
      "finding_kind": "clerical",
      "finding": "The generated fixture retains example AC, spec-sufficiency, verification-command, and MEU placeholders. It proves installed-template skeleton generation, not an execution-ready project plan.",
      "file_line": "scripts/tests/run_wp7_replay.py:123-164",
      "recommendation": "Keep the receipt scoped to bootstrap smoke coverage; fill project-specific content before using such a plan for real execution. No additional review round is required for this residual limitation.",
      "status": "accepted_risk"
    }
  ],
  "checklist_results": [
    {
      "check": "Rolling review approval state",
      "result": "pass",
      "command": "rtk proxy python -B -X utf8 -c 'import sys,json; from pathlib import Path; sys.path.insert(0,\"core/tools\"); import validate_closeout_artifacts as v; p=Path(\".agent/context/handoffs/2026-09-19-portable-adopter-bootstrap-implementation-critical-review.md\"); t=p.read_text(encoding=\"utf-8\"); s,n=v.check_review_state(t,str(p),\"execution\",\"2026-09-19-portable-adopter-bootstrap\",4); print(json.dumps(s)); print(v.check_approved_state(t,str(p),s,\"execution\",\"2026-09-19-portable-adopter-bootstrap\",4))'",
      "exit_code": 0,
      "evidence": "Native closeout state and approval functions accept round 4 with verdict approved and zero open blocking findings. Checked in memory; no state receipt file was written."
    }
  ]
}
```

**Verdict: approved.** Only this reviewer-owned rolling file was edited. No product, tests, plan, task, or work handoff changes; no git commit.
