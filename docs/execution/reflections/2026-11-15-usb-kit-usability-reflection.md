---
date: "2026-11-15"
project: "2026-11-15-usb-kit-usability"
meus: []
plan_source: "docs/execution/plans/2026-11-15-usb-kit-usability/implementation-plan.md"
template_version: "2.0"
---

# 2026-11-15 Meta-Reflection

> **Date**: 2026-11-15
> **MEU(s) Completed**: none (`meus: []`)
> **Plan Source**: docs/execution/plans/2026-11-15-usb-kit-usability/implementation-plan.md

---

## Execution Trace

### Friction Log

1. **What took longer than expected?**
   The full gate and the review loop. The full pytest run (`core/tools/tests` and `scripts/tests`) takes about 83 to 90 minutes, and H1-2 ran it twice: once before review and once on the state that the round 1 fixes made. The whole `test_fleet_usb.py` file takes about 16 minutes, so each Red and Green run of a coder row cost that much. The plan review used all 3 rounds of its cap and ended `changes_required` (H13, H14, H15 blocking, L02 not). The human then ruled "just fix them and run exectution", and the fixes were made without a fourth round. The execution review took 2 rounds. Three stops in that loop were not about the code: the review ledger refused round 2 on its default token budget of 21M until the human lifted it to 60M; the first round 2 dispatch was refused by the wrapper's schema check (a checklist result of `partial`) and had to run again; and during the green run another session edited `known-issues.md` by hand, which failed AC-21 (EA-15).

2. **What instructions were ambiguous?**
   Row H2-3b says that it proves "the six ids", but its validation command lists five. `FLEET-INSTALL-RETAINED-CREDITS-TESTS` (the sixth, from EA-2) is not in the tuple. The row's check still passes, and the H2-3b run of this closeout checks the sixth id in a separate command, but the row itself is weaker than its text. The plan also did not say what a reviewer does when a check cannot run in its sandbox; the reviewer wrote `partial`, which the verdict schema does not allow.

3. **What instructions were unnecessary?**
   The review ledger's default token budget. The human said "There should be no budget"; the round cap already limits the loop, and the token stop cost the human a turn for nothing.

4. **What was missing?**
   - A sandbox-writable temp folder for `run_pester.ps1`. Its self-check writes probe files under `[IO.Path]::GetTempPath()`, and the Codex review sandbox can write only under the receipts directory, so the self-check fails there. The fleet-agents reflection of 2026-11-05 named the same follow-up (its Next Day Outline, item 6), and it was not fixed, so round 1 here and the first round 2 attempt could not rerun Pester. The retry set `TMP` and `TEMP` to a folder under the receipts directory, and the suite then ran in the sandbox.
   - A test for each recovery path of the elevated child on Windows. Round 1 found F-001: a child that checkpointed every step and then died made the parent add a second `elevate` step, which the hub refuses.
   - A test for a tool that is already installed but not yet reachable. Round 1 found F-002: a snap PowerShell that was already there was never linked into `/usr/local/bin`, so an ssh command found no `pwsh`.

5. **What did you do that wasn't in the prompt?**
   - Wrote throwaway helpers in the session's scratchpad: the handoff builder (it fills the AC rows, the FAIL_TO_PASS table and the evidence.v1 records from receipts), the per-row Red and Green scripts, and the H1 runners.
   - Staged the core dispatch wrapper and the review ledger into a temporary folder by script, because the project's wrapper has no `-LoopId` and the core copy has placeholders.
   - Added a `-Tag` parameter to the dispatch row script, so that the round 2 retry got its own dispatch id and prompt and the first attempt's files stayed as they were.
   - Re-rendered `known-issues.md` from the YAML after another session's hand edit (EA-15), and kept the other session's hunks out of this plan's commit draft.

### Quality Signal Log

6. **Which tests caught real bugs?**
   - The independent review found the bugs that the tests missed: F-001 (AC-2) and F-002 (AC-10), both blocking, and F-003 (AC-18) and F-004 (privacy), both non-blocking. Each fix got a test written first and seen to fail (the `uk2-r1fix-red-*` receipts), and round 2 confirmed that each new test fails without its fix.
   - The plan-folder privacy scan found that an address range in the plan's own text counted as a hit (EA-1), and later that its link-local exemption was too broad (F-004, EA-14).
   - The full baseline run found two failing tests that the narrower planning run had not shown (EA-2); a clean export of `HEAD` proved that this plan did not cause them.
   - The AC-21 render check found another session's hand edit of `known-issues.md` (EA-15).

7. **Which tests were trivially obvious?**
   The presence checks for the README lines and the known-issue ids. They guard against a deleted line, and the review did not rate any test as Weak.

8. **Did pyright/ruff catch anything meaningful?**
   Neither is in this package's gate. The static gates are `refcheck` and `sanitize --verify`, compared with the row 1 baseline. They found the reference lines of EA-12 and EA-16, which were wording, not broken links.

### Workflow Signal Log

9. **Was the FIC useful as written?**
   Yes. The 26 ACs kept the work on the human's four complaints: no record written back, sudo-rs on Ubuntu, missing prerequisites, and RustDesk. The ruled scope (usability with full admin access, not hardening) kept the review from asking for an authenticated receiver or a narrower permission model.

10. **Was the handoff template right-sized?**
    Its sections fit. Generating the handoff from receipts by script let it survive the round 1 corrections with a rebuild instead of hand edits: 58 evidence records, each with its receipt's sha256, which round 2 checked.

11. **How many tool calls did this session take?**
    2392 in the session transcript, which since 2026-11-07 also holds the superseded hardening plan and its reviews; this plan's share is not split out. 73 automatic compactions are recorded for the session.

12. **Which rows were delegated, to which subagent (harness + model), and did any delegated result need rework?**
    Only the independent reviews, through Codex CLI `gpt-6.1-sol` and the ledger-bound `Invoke-CodexDispatch.ps1` wrapper. Plan rounds 1 to 3 and execution round 1 required rework. No build row was delegated.

### Decisions Log

| ID | Stage | Question | Resolution | Chosen | Source tag | Reasoning (why this; why the alternatives lost) | Human ref |
|----|-------|----------|------------|--------|------------|--------------------------------------------------|-----------|
| D-1 | planning | What happens to the human's four uncommitted kit edits? | autonomous | They become the baseline; row 1 backs them up first | Local Canon | The human tested that state and asked for fixes on top of it; the backup keeps it reversible | — |
| D-2 | planning | How do members send their record to the hub? | autonomous | An HTTP POST to `fleet_usb.py receive` on port 8771 with the drive's token | Research-backed | No share or credentials on each member, and curl is on all three systems before any install | — |
| D-3 | planning | How does the kit handle Wayland for RustDesk? | autonomous | Install the stable release, record `session_type`, file FLEET-RUSTDESK-WAYLAND | Research-backed | A preview build adds churn; forcing X11 changes the member's login unasked | — |
| D-4 | planning | Switch Ubuntu's sudo back to sudo.ws? | autonomous | No; find a working elevator and repair only a dangling sudo link | Research-backed | Changing the system default goes beyond what the kit needs | — |
| D-5 | planning | Where is the RustDesk password made and kept? | autonomous | At import on the hub, set over ssh, kept in a user-only file on the hub | Local Canon | The drive and the inbox are not secret stores | — |
| D-6 | planning | Does the send need TLS? | autonomous | No; plain HTTP on the LAN with the drive's token | Human-approved | The human ruled out a security scope; the record holds no secret | USER_EXPLICIT 2026-11-15 'i don't have issue with full admin access on these computers' |
| D-7 | planning | May the RustDesk password be a process argument on the member? | autonomous | Yes, for the one `--password` child only | Research-backed | RustDesk 1.5.3 takes it only as an argument | — |
| EA-1 | execution | The plan text wrote address ranges as literals | autonomous | Say the same thing in words | Local Canon | Keeps the privacy scan strict | — |
| EA-2 | execution | Two baseline failures outside the plan's known list | human | Excuse both for this plan; file a known issue | Human-approved | A clean export of HEAD fails them too | USER_EXPLICIT 2026-11-15 'Excuse both for this plan (Recommended)' |
| EA-3 | execution | Homebrew's precondition on macOS | autonomous | Homebrew needs only the account step; the order is unchanged | Local Canon | Otherwise AC-12 could never show Homebrew running | — |
| EA-4 | execution | Four details of the Windows prerequisites | autonomous | winget "already installed" is ok; the Store Python stub is ignored; uv through the existing installer | Research-backed | None narrows the plan | — |
| EA-5 | execution | Five details of the hub's receiver | autonomous | v2 records only, `prepare` works with no hub address, strict token and URL checks | Local Canon | The drive stays a full fallback | — |
| EA-6 | execution | Eight details of the member's send | autonomous | One final write, a reason for each failure, the drive copy stays `pending` on a stop | Local Canon | Keeps AC-7 exact | — |
| EA-7 | execution | Eight details of the hub's RustDesk side | autonomous | A strict release reader, a value-by-value settings merge, the password through stdin of ssh | Local Canon | A bad release is refused as a whole | — |
| EA-8 | execution | AC-11's step list and nine RustDesk member details | autonomous | `rustdesk` before `host_key` in the asserted list; the read-back decides, not the `--config` exit | Local Canon | AC-17 places the step there | — |
| EA-9 | execution | One AC-18 macOS test could not pass under the plan | autonomous | A setup-only change: persist `--config` first | Local Canon | No assertion changed (G36) | — |
| EA-10 | execution | Row 11b missed the excused tests' file | autonomous | Add the file to the row's pytest list | Local Canon | The check stays strict | — |
| EA-11 | execution | The linter refuses `[x] n/a` | autonomous | Mark no-op rows `[x]` with the basis in the row text | Local Canon | The linter's legend | — |
| EA-12 | execution | Gate false positives at row 11b | autonomous | Reword references, avoid the deny-term call, change a fixture tag | Local Canon | No check narrowed, except the link-local exemption, which EA-14 corrected | — |
| EA-13 | execution | The state id moved with each row mark | autonomous | `--state` leaves out this plan's task.md only | Local Canon | H1-6b could never pass otherwise | — |
| EA-14 | execution | Review round 1 findings F-001 to F-004 | autonomous | Fix all four test-first | Local Canon | Round 2 confirmed each fix | — |
| EA-15 | execution | Another session's hand edit of known-issues.md | autonomous | Re-render from the YAML; keep its hunks out of this plan's commit | Local Canon | The markdown is rendered, never hand-edited | — |
| EA-16 | execution | Gates failed on handoff wording after the rerun | autonomous | Reword; rerun only the gates | Local Canon | The state id did not change | — |
| H-1 | execution | The plan review reached its round cap | human | Fix the round 3 findings and execute | Human-approved | The human's direction | USER_EXPLICIT 2026-11-15 'just fix them and run exectution' |
| H-2 | execution | The ledger refused round 2 on its token budget | human | Lift the budget to 60M | Human-approved | The human's direction | USER_EXPLICIT 2026-11-15 'There should be no budget but for now increase it to 60M' |

---

## Pattern Extraction

### Patterns to KEEP
1. Generate the handoff's evidence records from receipts by script, and keep the superseded receipts beside the new ones (`prev-h1-2-r0/`).
2. Bind the evidence to a state id, and leave out of that id only the bookkeeping file that the closeout marks.
3. When a gate fails on a dispatch artifact, read the wrapper's `status.json` before acting: here it named the schema violation, while the console only said that there was no verdict.

### Patterns to DROP
1. Opening a review loop with the ledger's default token budget.
2. Carrying a known tool limit from one reflection to the next without fixing it (the Pester runner's temp folder).

### Patterns to ADD
1. Give each script that a reviewer runs a temp folder that its sandbox can write, or tell the reviewer how to set one in the prompt.
2. Tell the reviewer the schema's allowed checklist results in the prompt: a check that cannot run is `n/a` with the reason.
3. For each step that can resume after a crash, test the crash after the last checkpoint, not only after an early one.

### Calibration Adjustment
- Estimated time: one execution pass and one review loop, with the human rows at the human's pace
- Actual time: one day of execution after a 3-round plan loop; 2 execution review rounds; two full gate runs of about 83 to 90 minutes each
- Adjusted estimate for similar MEUs: budget one full gate rerun after review corrections, and one dispatch retry for sandbox or schema issues

---

## Next Session Design Rules

```
RULE-1: A script that the reviewer runs must work in the reviewer's sandbox, or the prompt says how.
SOURCE: run_pester.ps1's self-check failed in the Codex sandbox in two plans (temp folder not writable)
EXAMPLE: "run run_pester.ps1" → "set TMP and TEMP to a folder under the receipts directory, then run run_pester.ps1"
```

```
RULE-2: Open a review loop with a token budget large enough that only the round cap stops it.
SOURCE: the ledger refused execution round 2 at 18.3M of a 21M default; the human lifted it
EXAMPLE: review_ledger.py begin ... → review_ledger.py begin ... --token-budget 60000000
```

```
RULE-3: Test each crash-resume path at its last checkpoint as well as an early one.
SOURCE: execution review round 1, F-001 (a child that died after its last checkpoint)
EXAMPLE: "child dies after step 2" → "child dies after step 2, and after host_key"
```

---

## Next Day Outline

1. The human reviews the commit draft `C:/Temp/agentic-framework/receipts/uk2-commit-draft.txt` and its manifest, and decides on a commit. No agent commit or push. The FLEET-DOCKER-CI-LANE-UNTRACKED hunks belong to another session and are not in the manifest.
2. The human rows on the human's words: 11a (hub prepare and receive), 12 to 15 (a Windows member, a rerun, an Ubuntu member with sudo-rs, a macOS member).
3. Follow-up: give `run_pester.ps1` a temp folder that a review sandbox can write (third report of this limit).
4. Follow-up: add `FLEET-INSTALL-RETAINED-CREDITS-TESTS` to the H2-3b id tuple of a later plan's known-issue check.
5. Follow-up: a proposal to remove or raise the review ledger's default token budget, for the human to decide.
6. Leftover scratch folder `C:/Temp/zorivest/usb-kit-plan/symtest`; its removal was blocked and waits for the human.

---

## Efficiency Metrics

| Metric | Value |
|--------|-------|
| Total tool calls | 2392 in the session (since 2026-11-07, with the superseded hardening plan) |
| Time to first green test | row 2 (WP-K1, Unix and the record) |
| Tests added | `test_fleet_usb.py` now holds 231 tests and `SetupWindowsUsb.Tests.ps1` 76 Pester cases; `check_kit.py --selftest` 61 cases |
| Codex findings | plan: 3 rounds to the cap, last round H13 to H15 blocking and L02; execution: R1 F-001 and F-002 blocking, F-003 and F-004 not, R2 approved |
| Handoff Score (X/7) | 7/7 |
| Rule Adherence (%) | 90 |
| Prompt→commit time | n/a (draft only; no commit) |
| Compactions (auto/manual) | 73 (73/0) |

### Rules Sampled for Adherence Check

| Rule | Source | Followed? |
|------|--------|-----------|
| Never auto-commit or push | AGENTS.md §Commits | Yes: no commit; the draft goes to the human |
| The implementer never authors approved | AGENTS.md §Independent Review | Yes: the schema-refused round 2 was dispatched again, not edited |
| Tests first, then implement | AGENTS.md §Testing / TDD | Yes: red receipts for every coder row and for F-001 to F-003 |
| Never modify tests to make them pass | AGENTS.md §Testing / TDD (G36) | Yes: EA-9 and the `config_exit` stub are setup changes, logged and reviewed |
| A gate waiver is the human's | human-decision-protocol.md | Yes: EA-2 asked first |
| No machine name, address or user path in a tracked file | the plan's Privacy scan | Yes, after EA-1, EA-12 and EA-16 rewordings |

---

## Instruction Coverage

```yaml
schema: v1
session:
  id: "883ebdca-e7f1-4e85-80f4-31c8c9ceae91"
  task_class: tdd
  outcome: success
sections:
  - id: authority_and_approval
    cited: true
    influence: 3
  - id: planning_contract
    cited: true
    influence: 2
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
  skills: [cli-dispatch]
  refs: [human-decision-protocol.md, REVIEW-TEMPLATE.md, HANDOFF-TEMPLATE.md, REFLECTION-TEMPLATE.md, review-vocabulary.yaml]
decisive_rules:
  - "P0:never-auto-commit"
  - "P0:implementer-never-authors-approved"
  - "P1:tests-first-then-implement"
  - "P1:never-modify-tests-to-pass"
  - "P1:gate-waiver-is-human"
conflicts:
  - "the harness's Co-Authored-By attribution reminder vs the fleet MVP plan's no-trailer rule; the plan's rule followed in the commit draft"
  - "the review ledger's default 21M token budget vs the quality-first rule that tokens are never a constraint; the human lifted it to 60M"
  - "row H2-3b's text names six known-issue ids, its command checks five"
note: "Both blocking review findings were crash-resume and already-installed paths that the plan's tests did not reach."
slim_candidate: [review-ledger-default-token-budget]
overthinking_observed: false
review_churn:
  rounds_to_approval: { plan: 3, execution: 2 }
  findings_per_round:
    - { round: 1, critical: 0, high: 2, medium: 1, low: 1 }
    - { round: 2, critical: 0, high: 0, medium: 0, low: 0 }
  churned_findings: 0
  finding_categories: { contract_drift: 3, boundary_validation: 1 }
  verdicts: { changes_required: 4, approved: 1 }
meu_work_classes: []
compactions: { count: 73, auto: 73, manual: 0 }
```
