---
date: "2026-10-20"
review_mode: "plan"
target_plan: "docs/execution/plans/2026-10-20-review-limits-parameters/implementation-plan.md"
verdict: "corrections_applied"
findings_count: 5
template_version: "2.2"
requested_verbosity: "standard"
agent: "gpt-6.1-sol"
loop_id: "review-limits-parameters-plan-2026-10-20"
round: 1
---

# Critical Review: review-limits-parameters

> **Review Mode**: `plan`
> **Verdict**: `changes_required`

## Intent Anchor

"Make review round caps and token budgets setup choices in the repo, adopted by each plan and execution as tighten-only defaults, with loosening only through a verified human-typed offer."

The plan substantially addresses setup and inheritance, but its authorization contract and final-audit fallback do not yet preserve that intent. Its main workflow-cap oracle also demonstrably passes with required cap replacements missing.

## Scope

Reviewed `docs/execution/plans/2026-10-20-review-limits-parameters/implementation-plan.md` and `task.md` against the human request supplied in the review prompt, the plan-review protocol, REVIEW-TEMPLATE 2.2, and the named live tools, workflows, templates and adoption documents. Also inspected the offer schema, fixture builder, closeout validator, durable-evidence validator, review vocabulary, registry binding and latest peer plan-review handoff.

This is an unstarted plan: all implementation status cells are unchecked; the three proposed test files, new config and implementation handoff are absent. Baseline HEAD is `d698342c2ce5cae8d1d3fdec38b04be026353810`; initial Git status names only the untracked plan directory. The dispatch argv and live registry both identify this reviewer as `gpt-6.1-sol`; the ledger producer is `claude-opus-coordinator`.

No product suite or implementation selftest was run. Verification comprised source inspection, the task-contract linter, argument-parser checks and disposable in-memory probes. The new feature is not implemented, so proposed behavior is assessed as a specification, not reported as a runtime result.

## Findings

All findings have **High confidence** and concern the **deliverable**. References abbreviated below resolve under `docs/execution/plans/2026-10-20-review-limits-parameters/` unless a full live-source path is given.

| # | Severity | Blocking | Kind | Finding | File:Line | Recommendation | Status |
|---|----------|----------|------|---------|-----------|----------------|--------|
| F-001 | High | yes | behavior | **AC-13 does not require the human to type the offered values.** Its sufficient conditions are an `authorization/1` that verifies and an equal offer block. Live `_verify_reference` accepts `form: reply`, extracts the offer from the assistant presentation, and verifies the human's bare acceptance word. An in-memory probe accepted exactly this arrangement with human text `yes`. Extending the offer parser to /2 leaves this provenance unchanged: an assistant-authored looser cap or `off`, followed by `yes`, meets AC-13 while violating D-2 and the goal's human-typed-value rule. None of AC-13's negative cases distinguishes these two authorization forms. | `implementation-plan.md:198`; live `core/tools/run_parameters.py:1419` and `:1435` | Require the loosening values themselves in a verified human record, for example a self-contained /2 offer. Add a negative case for an assistant-authored /2 offer accepted by a human's bare word, paired with a positive human-typed numeric/off offer. Preserve ordinary reply-form authorization for its existing uses. | open |
| F-002 | High | yes | control-defeat | **AC-15's missing-ledger fallback bypasses limits authorization.** `mechanism: verdict-to-state-transition`. The plan calls `limits-check` only from `begin`, but final audit may take `task.review_limits.execution_rounds` when no execution ledger exists. Existing `_produce` calls `_verify_plan`; `_check_block` and `_inherit` validate only `run_parameters`, ignoring the sibling limits. Thus an otherwise valid /1 grant without any offered limits, no execution ledger, and a hand-edited `execution_rounds: 7, basis: loosened` yields cap 7 under the specified fallback. The live review-state and approval functions accept an approved seventh-round review at cap 7 and reject it at cap 6. The authorization producer has been skipped, yet closeout accepts the enlarged cap. A missing ledger can also erase a tighter flag-derived cap. | `implementation-plan.md:200` and `:401`; `task.md:44`; live `core/tools/run_parameters.py:4058` and `:1754` | Use the same validated resolver and carrier-equality/loosening checks in final audit, including fallback paths. Distinguish genuine legacy absence from missing required new-loop state; refuse malformed existing ledgers rather than falling back. Test no-ledger + unauthorized loosened task, missing tightened-loop state, malformed ledger, and the authorized round-7 continue case. | open |
| F-003 | High | yes | control-defeat | **The AC-17 checker false-passes materially missing cap replacements.** `mechanism: task-row-completion-predicate`. Row 5a only recognizes digits immediately before `round`/`rounds`. Live fixed caps at delegated-plan-creation:37 (`round cap (3)`), create-plan:656 (`round cap (6)`) and execution-session:190 (`execution = 6`) are invisible. In an in-memory copy of all five input files, replacing only regex-matching phrases made the exact row-5a predicate return an empty violation list while all three fixed caps remained. Its line-wide `default`/pointer exemption can also hide a conflicting sentence; conversely the regex flags an illustrative non-cap sentence such as `An approved review at 7 rounds is accepted under the loop cap.` This violates AC-17's promised replacement control, not merely regex style. | `task.md:46`; `implementation-plan.md:202` | Check a bounded inventory of operative cap statements and their replacement with source references, including the three live forms. Prove that leaving each operative fixed cap unchanged fails. Treat illustrative round counts separately and scope exemptions to the actual cap statement. | open |
| F-004 | Low | no | clerical | **Two touched workflow examples cannot open their loops.** The delegated-plan `begin` at 247–250 and dispatch-skill example at 309–312 omit required `--goal-anchor` and `--ac-file`. The delegated example's argv exits 2 before `cmd_begin`, so merely updating adjacent cap prose does not make that example consume plan parameters. The actual caller and required arguments are evident; this is an existing example correction, not a request for another control. | `implementation-plan.md:233` and `:235`; live `core/.agent/workflows/delegated-plan-creation.md:247`, `core/.agent/skills/cli-dispatch/SKILL.md:309` | Include the goal sentence and canonical implementation-plan path in both `begin` examples while touching these sections. | open |
| F-005 | Low | no | clerical | **The ledger refusals are assigned the wrapper's exit code.** AC-8/9/10/13 and the boundary table specify ledger exit 9; live `review_ledger.main` maps `Refuse` to 1. Exit 9 belongs to the dispatch adapter. No ledger-wide exit-contract migration is proposed. | `implementation-plan.md:177`, `:193`–`:198`; live `core/tools/review_ledger.py:1868` | State ledger refusal = 1, fail-closed = 3, usage = 2; reserve 9 for the dispatch wrapper or the run-parameters CLI where applicable. | open |

## Checklist Results

### Plan Review

| Check | Result | Observation |
|---|---|---|
| PR-1 Plan/task alignment | pass | Four work packages map to rows 1–5, with AC checks and H1/H2 closeout. The final audit change is explicitly in WP-3. |
| PR-2 Not started | pass | All implementation rows unchecked; new config/tests and project implementation handoff absent. |
| PR-3 Task contract completeness | pass | Executed linter: 35 rows, 10 columns, 33 fully checked, two source-read exemptions; dependencies resolve and are acyclic. |
| PR-4 Validation realism | fail | F-003 demonstrates a missing-deliverable false pass. New test paths are scheduled outputs, not nonexistent-tool blockers. |
| PR-5 Source-backed planning | partial | Defaults and scope trace to the human request and real code. D-1 is candidly unresolved; its `Human-approved` label overstates its status. F-001/F-002 conflict with D-2. |
| PR-6 Handoff/corrections readiness | pass | Canonical project handoff and both rolling reviews are named. Round-1 census is not applicable. Corrections belong to `/plan-corrections`. |
| PR-7 C2 scope discipline | pass with notes | No disguised deferred work or invented MEU target found; dispositions below. |
| PR-8 Reachability and negative oracles | fail | Authorization form is insufficient (F-001), final-audit fallback bypasses it (F-002), and workflow oracle false-passes (F-003). |
| PR-9 Single-statement discipline | partial | Shape/limit descriptions recur in the shared contract, boundary table, ACs, task and decision log. Centralize them during correction; no additional materially different cap contract was found beyond the reported issues. |

### Acceptance-criterion falsification audit

These are assessments of the **planned** tests, not claims that unwritten tests passed.

| ACs | Assessment of producer and negative oracle |
|---|---|
| AC-1–4 | Defaults equal the live five-mode maps. Equality, changed-byte, invalid-input/no-write and verify-refusal cases are meaningful. Flags/config/verify/selftest exist as extension points; the proposed flags do not exist yet. Keep invalid inputs checked before any instantiate mutation. |
| AC-5–6 | A nonconstant repo cap and malformed-present versus absent distinction can falsify a resolver that ignores configuration or silently falls back. Define the repo root consistently for installed and raw-package layouts. |
| AC-7–9 | Basis computation, strict parsing, sibling comparison and looser-flag refusal have meaningful negatives. Bind equality to the two canonical carriers even if `--ac-file` is an alternate filename; numeric comparisons must reject booleans, zero and null. F-004/F-005 need small corrections. |
| AC-10–11 | Explicit `off`, huge measured usage, numeric budget 1, zero/null load refusal and unchanged non-token stops are meaningful. Preserve numeric equality boundaries and test `continue --rounds` on an off loop, as well as refusal of `--tokens`. Do not accept a hand-edited 0/null via the existing `or` fallback. The ledger remains mutable state; a plain SHA provenance field does not authenticate arbitrary valid-looking hand edits. |
| AC-12 | Missing `limits_source` is compatible with the existing optional-key allowlist. An actual current numeric ledger without that key evaluated successfully in the probe. Preserve its stored budget and grants rather than re-resolving current repo defaults. Prospective before/after fixture comparison is appropriate; post-change compatibility has not been executed. |
| AC-13–14 | Disabled/manual/legacy/mismatch negatives can fire, but omit the human-typed-value distinction in F-001. The live `_ValueParser('3')` returns a string: accepting new numeric fields requires parser work as well as `_offer_types_ok`; pair the quoted-string refusal with a successful unquoted integer. The /1 exact-key rejection must remain version-specific. |
| AC-15–16 | The round-7 with/without continue test can distinguish caps, but misses F-002's no-ledger path. Read-only hashes for success and refusal are appropriate. The new resolver must run against the real repository/ledger, not accidentally resolve configuration relative to the temporary final-audit snapshot. |
| AC-17 | Demonstrated false pass and false-fail risks: F-003. Step-0 token presence alone is weaker than observing the specified resolution/write instructions; review their actual content. |
| AC-18 | Template/version checks can detect the primary edits. The row-5c one-liner does not check the `{configured-cap}` source or blockless lint behavior; AC-18 still explicitly requires those checks. Neither linter nor closeout selftest is listed in the verification commands: add their existing `--selftest` invocations when implementing this AC. |
| AC-19–20 | Required strings and refcheck are runnable but remain presence/link checks; inspect the actual setup guidance and resolution-order text. New config/schema paths are scheduled. |
| AC-21 | Keeping USD handling unchanged fits the stated provisional recommendation. Diff review plus credits suites can detect regressions. Pester is installed; a deliberately failing disposable Pester container produced `FailedCount=1` and nonzero `$LASTEXITCODE=2` here, so a swallowed-failure claim was not substantiated in this environment. |

### D-1, D-5, D-8 and scope dispositions

- **D-1:** Honest and sufficient for this planning review as a clearly disclosed provisional recommendation, not evidence of human approval. The original request does not explicitly ask to remove USD caps. The plan quotes the ambiguity, asks for confirmation and requires a later human execution instruction. Change the source label to pending human confirmation, and retain that unresolved interpretation at the execution gate; `yes` must not be represented as unambiguous consent to either USD behavior.
- **D-5:** A sibling block is a reasonable way to let repo defaults/tightening work without activating run parameters or migrating `BLOCK_KEYS`, `_within` and grouping carriers. It creates a separate validation boundary: do not assume those existing functions authorize the sibling. That boundary is exactly why F-002 matters.
- **Off Windows / disabled:** The repo policy file is absent. A direct activation probe returns `disabled / policy_missing`. The ordinary `status` command instead reports disabled because this sandbox user's Git ownership check fails first; it does not independently reproduce the planner's exact `policy_missing` CLI output. Live `_gate` has no OS test: non-Windows disablement currently follows instantiate removing required components. AC-13's new off-Windows refusal must be explicit or proven with an otherwise activated fixture, not inferred from an inactive fixture that would refuse on any OS.
- **D-8:** Using `rounds_allowed()` fixes the real hard-coded-6 mismatch: the live function includes continuation grants, including legacy grants. Its fallback must not become an alternate unverified loosening path (F-002).
- **C2:** Grouping-line syntax and plan-level controls for the other three modes are outside the explicit plan/execution request. The other modes still use the shared repo resolver; this is a modest, disclosed extension. Mechanism/scaffolding thresholds are distinct existing controls. Keeping adopter config unpinned is substantiated by the distinction between mutable setup configuration and pinned tool components. USD scope remains provisional under D-1. The excluded SVG actually says `≤3 rounds` and `≤6 rounds` without labeling them defaults: recording that residual documentation limitation is appropriate; it is not a missing code deliverable under these ACs.

### Referenced artifacts and live command surfaces

All currently invoked tools exist: `core/tools/review_ledger.py`, `run_parameters.py`, `durable_evidence.py`, `issue_triage.py`, `lint_task_contract.py`, `validate_closeout_artifacts.py`, `scripts/instantiate.py` and `scripts/refcheck.py`. The apparently missing `tools/validate_agent_files.py` resolves correctly after the plan's `Push-Location core`. The three new tests, review-limits config, new offer-schema version and closeout artifacts are scheduled outputs. The existing offer schema is `core/.agent/run-parameters/schemas/run-parameters-offer.v1.schema.json`.

The lint, closeout, durable-evidence and issue-triage flags/verbs named in the task are present in source. Instantiate has the cited credits-start-policy precedent and verify/selftest entrypoints. No unsupported new flag is mistaken for an existing deliverable: the plan explicitly schedules its implementation. The package has neither `docs/BUILD_PLAN.md` nor a root MEU registry, as claimed. The plan's statement that this environment has no RTK is stale; RTK is available, and all review shell commands used its prefix.

### Durable observations

```json
{"schema_version":"evidence.v1","check_id":"task-contract","command":"rtk proxy python -B -X utf8 core/tools/lint_task_contract.py --task docs/execution/plans/2026-10-20-review-limits-parameters/task.md","cwd":"P:/agentic-framework","scope":"unstarted task table","phase":"static","exit_code":0,"result":"pass","tested_state":"HEAD d698342c2ce5cae8d1d3fdec38b04be026353810 plus untracked review-limits-parameters plan","output":"OK: 35 row(s); 10-column table (with builder_model); 33 row(s) fully checked; dependencies resolve and are acyclic; 2 row(s) exempt (view_file): H1-5, H2-1"}
```

```json
{"schema_version":"evidence.v1","check_id":"authorization-boundary","command":null,"procedure":"Inspected _check_authorization, _verify_reference, _check_block and _inherit. Executed an in-memory Python probe using the real fixture offer_lines/authorization/make_block helpers, a valid /1 assistant offer and a typed external human record containing only yes. Replaced only _load_transcript with an in-memory Transcript; real type, parent-chain, payload, digest and consent checks ran. Passed the real _inherit a valid carrier whose sibling review_limits had execution_rounds 7 and basis loosened; no offer limits key was present.","observer":"gpt-6.1-sol","cwd":"P:/agentic-framework","scope":"existing authorization semantics used by AC-13 and AC-15","phase":"manual","exit_code":null,"result":"pass","tested_state":"live run_parameters.py at review time; no feature implementation","output":"authorization_kind v1; reference_accepted reply human_text='yes' offer_source=assistant; carrier_inheritance_accepted {'decisions': 'hdp', 'commit_plan': False, 'exec_after_plan': False, 'commit_exec': False, 'push': 'never'}; verified_offer_has_review_limits False; AC15_missing_ledger_fallback_cap 7; unquoted_integer_parser '3' str"}
```

```json
{"schema_version":"evidence.v1","check_id":"final-cap-oracle","command":null,"procedure":"Called live check_review_state and check_approved_state on an in-memory execution review targeting 2026-10-20-probe, verdict approved, an empty correctly headed findings table and six Recheck headings. Compared cap 6 with the plan-prescribed missing-ledger task fallback 7. This probes the downstream functions; the proposed fallback itself is not implemented.","observer":"gpt-6.1-sol","cwd":"P:/agentic-framework","scope":"final-audit downstream round acceptance","phase":"manual","exit_code":null,"result":"pass","tested_state":"live closeout validator; synthetic in-memory review","output":"cap 6 REFUSE review memory-only.md has 7 round(s), over the cap of 6; cap 7 ACCEPT approved at round 7 of 7, 0 open blocking findings"}
```

```json
{"schema_version":"evidence.v1","check_id":"ac17-missing-deliverable-probe","command":null,"procedure":"Read the five files named by task row 5a into memory. Used its exact regex and exemption list. Replaced every regex-matching number-before-round phrase with configured cap, then evaluated its bad-list comprehension without writing any file. Inspected the remaining live cap lines. Also evaluated an illustrative round-7 non-cap sentence and a fixed-cap sentence containing the word default.","observer":"gpt-6.1-sol","cwd":"P:/agentic-framework","scope":"AC-17 negative oracle","phase":"manual","exit_code":null,"result":"pass","tested_state":"live five workflow/doc inputs, mutated only in memory","output":"AC17_in_memory_mutation_oracle_exit 0; material_fixed_cap_remains: round cap (3); material_fixed_cap_remains: round cap (6); material_fixed_cap_remains: execution = 6. Illustrative round-7 sentence flagged; Ignore the repo default; the review stops at 3 rounds. exempted."}
```

```json
{"schema_version":"evidence.v1","check_id":"begin-example-argv","command":"rtk proxy python -B -X utf8 -c \"import subprocess,sys; p=subprocess.run([sys.executable,'-B','core/tools/review_ledger.py','begin','--loop-id','planreview-probe-2026-10-20','--review-mode','plan','--producer','Claude'],capture_output=True,text=True); print('native_exit='+str(p.returncode)); print(p.stdout); print(p.stderr)\"","cwd":"P:/agentic-framework","scope":"delegated begin example argument contract","phase":"targeted","exit_code":0,"result":"pass","tested_state":"live ledger argparse; no ledger written","output":"native_exit=2; USAGE: see review_ledger.py --help; error: the following arguments are required: --goal-anchor, --ac-file. Outer exit 0 is the probe completing; native exit 2 is the observed refusal."}
```

```json
{"schema_version":"evidence.v1","check_id":"legacy-and-activation","command":null,"procedure":"Loaded the registered review loop read-only and evaluated stops/tokens_spent on in-memory copies. Inspected the loader allowlist and continue implementation. Checked the repo policy path and called _activation with the real project top, bypassing only repository discovery to distinguish policy absence from the sandbox Git-ownership failure.","observer":"gpt-6.1-sol","cwd":"P:/agentic-framework","scope":"legacy representation and disabled-policy baseline","phase":"manual","exit_code":null,"result":"pass","tested_state":"current numeric ledger without limits_source; live tools","output":"legacy_missing_limits_source True; numeric_budget 10500000; legacy_stops []; token_budget 0 and None both currently yield (0, 3500000, 10500000), confirming the fallback that AC-10 must replace; rounds_allowed_current 3; explicit_continue_adds 4; policy_file_exists False; direct_activation disabled policy_missing"}
```

## Verdict

`changes_required` — intent achieved: **partial**. Resolve F-001 through F-003 in the plan and its negative tests, then resubmit for independent review. F-004/F-005 and the pending D-1 label are non-blocking corrections. The setup choices, explicit off representation, ordinary tightening, sibling-block architecture and preservation of existing numeric ledgers are otherwise coherent proposals.

Only this canonical review handoff was written. No plan, product, tool or test file was edited, and no commit was created.

## Corrections Applied (planner, 2026-10-20, before round 2)

| Finding | Correction |
|---|---|
| F-001 | AC-13 and the `limits-check` boundary row require `authorization/1` with `form: self-contained`, so every limit value is human-typed. Added a negative case for a `form: reply` assistant offer with a bare accept, and positive cases for numeric and `off` values. |
| F-002 | AC-15 and D-8: one resolver, `audit_round_cap`. It uses the `exec-<slug>` ledger's `rounds_allowed()` (fail-closed if malformed or the wrong mode). With a task block and no ledger it refuses `exec_ledger_missing`. Only a legacy task with no block uses the repo file, then 6. The task block is never a cap on its own. Added fixtures for the unauthorized fallback, malformed and wrong-mode ledgers, and the legacy path. |
| F-003 | AC-17 now uses a bounded `FIXED_CAP_INVENTORY` (24 phrases across five files), checked by `check_ac17.py` in the plan folder. The script also fails against the `d698342` text, which proves the check can fail. Task row 5a runs it. Tested: 24 problems at the base commit, 0 on clean text. |
| F-004 | Files Modified: `delegated-plan-creation.md:247` and `cli-dispatch/SKILL.md:309` begin examples gain `--goal-anchor` and `--ac-file`. |
| F-005 | Ledger refusals are exit 1 throughout, with a note in the shared contract that the dispatch wrapper maps them to 9. Fail-closed is 3, usage is 2. |

`task.md` re-lints clean (35 rows). Round 2 is blocked by the ledger's token stop until a named human runs `continue`.

## Recheck (2026-10-20) — Round 2

**Workflow:** `/plan-critical-review` recheck  
**Agent:** `gpt-6.1-sol` (confirmed by round-2 dispatch `cmd_line.txt`, argument 6)  
**Verdict:** `changes_required` — PR-6 procedural precondition failure; substantive corrections are not adjudicated this round.

### Intent Anchor

"Make review round caps and token budgets setup choices in the repo, adopted by each plan and execution as tighten-only defaults, with loosening only through a verified human-typed offer."

The review must establish whether executing the plan delivers that goal. Intent remains **partial / not re-established** because the required correction evidence is absent.

### Scope and Procedural Gate

Targets remain `docs/execution/plans/2026-10-20-review-limits-parameters/implementation-plan.md` and `task.md`. Implementation remains unstarted: no numbered implementation row is checked and the project's implementation handoff is absent. The plan-folder `check_ac17.py` is a planning validation artifact, not evidence that implementation has started.

The supplied correction table at lines 125–135 names no blast-radius census receipt and provides no per-hit `file:line` dispositions. A search of the complete plan, task, and correction section finds no census reference or disposition log. The finding-to-correction summary is not the raw unfiltered sweep or its per-hit disposition log.

[PR-6](../../../core/.agent/workflows/plan-critical-review.md#plan-review-checklist-required) requires both artifacts on round 2+: "return `changes_required` naming only that, and do not review the corrected content this round." The workflow's **Verdict Rule** explicitly treats this as a precondition failure before severity, with nothing to rate. Accordingly, this round adds **no severity-rated finding**, invents no AC violation, and does not close or reassert any delivery finding. An empty structured findings array here represents that procedural exception, not approval. The v2 template's generic requirement for a blocking finding on every refusal does not provide a representation for this workflow exception; do not manufacture a delivery defect to fill it.

### Prior Pass Summary

| Finding | Prior Status | Round 2 Result |
|---|---|---|
| F-001 | open; correction claimed | Not adjudicated: PR-6 precondition failed. |
| F-002 | open; correction claimed | Not adjudicated: PR-6 precondition failed. |
| F-003 | open; correction claimed | Not adjudicated: PR-6 precondition failed. |
| F-004 | open; correction claimed | Not adjudicated: PR-6 precondition failed. |
| F-005 | open; correction claimed | Not adjudicated: PR-6 precondition failed. |

### Findings

None added. The sole reason for refusal is the missing correction census and per-hit dispositions. D-1, D-5, D-8, C2, entrypoint enforcement, legacy compatibility, and AC negative-test adequacy have no new substantive verdict this round.

### Checklist Results

| Check | Result | Evidence |
|---|---|---|
| PR-2: unstarted plan | pass | No checked numbered implementation row; implementation handoff absent. |
| PR-6: round-2 correction census | fail | No named raw census receipt or per-hit disposition log in the resubmission. |
| Explicitly requested AC-17 rerun | pass (negative baseline only) | Script exit 1; baseline self-check reports 24 problems; live tree reports 24 problems. |
| PR-1, PR-3–5, PR-7–9 and substantive fix verification | n/a | Withheld under the PR-6 procedural gate. No implementation or feature tests run. |

```json
{"schema_version":"evidence.v1","check_id":"r2-pr6-correction-census","command":null,"procedure":"Read both complete target files and the existing review's Corrections Applied section (lines 125-135); searched those resubmission surfaces for census, disposition and confirmed-consistent. The correction section contains only five finding-level descriptions and a lint/token-stop note; it names neither a raw census receipt nor a per-hit disposition log. Prior Round 1 uses of census/dispositions describe that earlier review, not correction evidence.","observer":"gpt-6.1-sol","exit_code":null,"result":"fail","evidence":"Round-2 correction census receipt reference absent; per-hit file:line dispositions absent.","output":"No census receipt reference or per-hit disposition in plan, task or Corrections Applied."}
```

```json
{"schema_version":"evidence.v1","check_id":"r2-ac17-explicit-rerun","command":"rtk proxy python -B -X utf8 docs/execution/plans/2026-10-20-review-limits-parameters/check_ac17.py","cwd":"P:/agentic-framework","scope":"Current unimplemented live workflow text; explicitly requested rerun only","phase":"static","exit_code":1,"result":"pass","tested_state":"Current working tree; script compares baseline d698342","output":"self-check: 24 problems at d698342 (oracle can fail)\nAC-17 FAIL: 24 problems in the working tree","evidence":"Live diagnostics explicitly include round cap (3), round cap (6), execution = 6 and both parenthesized inequality forms. This is an expected negative baseline, not an implementation failure or proof that the oracle passes only correct replacements."}
```

The AC-17 command was run because the human explicitly requested it. Its result establishes that this script fails on the present tree. It does **not** establish mutation coverage, sufficiency of source references, or closure of F-003; those conclusions remain withheld at the procedural gate.

### Verdict and Follow-up

`changes_required` — provide the corrector's untruncated old/new-value census receipt(s), name their paths in the correction log, and assign every hit an `updated` or `confirmed-consistent` disposition. Then resubmit through the authorized review process. This review does not perform corrections or authorize another round past ledger limits.

Round 1 and the planner's correction table are preserved. Only this rolling review handoff was edited in the repository. No plan, product, tool or test was changed; no commit was created. The timestamp receipt is `C:/Temp/agentic-framework/receipts/review-limits-plan-r2-stamp.txt`. The explicit final JSON requirement takes precedence over appending a non-JSON timestamp to the final response.

Final `rtk git status --short` (exit 0) also showed changes that appeared during this review in `core/tools/run_parameters.py`, `core/tools/tests/test_commit_batch.py`, `core/tools/tests/test_run_parameters.py`, and untracked `core/tools/run_parameters.py.orig`. This reviewer did not write those files; they are concurrent workspace activity and were not assessed. The initial status showed only the untracked review and plan directory.

🕐 Completed: 2026-10-20 15:02 (EDT)

## Corrections Applied — Census Addendum (planner, 2026-10-20, before round-2 resubmission)

This answers the Round 2 procedural gate (PR-6, `plan-corrections.md` Step 5c). The census found three more sites the round-1 corrections had missed (marked **updated** below). They are now fixed.

**Census receipt (raw, untruncated):** `C:/Temp/agentic-framework/receipts/census-rl-r2/census-review-limits-r2.txt`, 191 lines, sha256 `4781c3f2be99da7fc39f904605376400ac2ec1bdc8f85a01a93e54542511f0a3`. It was produced by `rtk proxy rg -F -n` over both plan files, on the final text after all edits. Each value is followed by its `# rg exit` code. No sweep returned an error (>1).

**Values and the variants swept (35):**

| Correction | Values swept |
|---|---|
| F-005 exit codes | `exit 9`, `exits 9`, `code 9`, `to 9`, `exit 1`, `exits 1` |
| F-001 loosening provenance | `form: self-contained`, `form: reply`, `self-contained`, `bare accept`, `human-typed`, `verified offer`, `bound authorization`, `verifies against the transcript`, `authorization/1`, `limits-check`, `loosened` |
| F-002 audit cap | `falls back`, `then 6`, `execution_rounds`, `EXEC_REVIEW_MAX_ROUNDS`, `audit_round_cap`, `exec_ledger_missing`, `rounds_allowed`, `fallback`, `final audit`, `final-audit` |
| F-003 AC-17 oracle | `Grep:`, `regex`, `fixed round cap`, `FIXED_CAP_INVENTORY`, `check_ac17`, `rl-ac17` |
| F-004 begin examples | `--goal-anchor`, `--ac-file` |

`exit 9`, `exits 9`, `code 9`, `verified offer`, `Grep:` and `fixed round cap` return rg exit 1 (no stale site left). The remaining `9` hits are the deliberate wrapper-mapping notes.

**Correction log (each `file:line` in the receipt; P = `implementation-plan.md`, T = `task.md`):**

| Site | Values hit | Disposition |
|---|---|---|
| P:29 | `falls back` | confirmed-consistent: Context describes today's `tokens_spent` behavior, which the plan fixes |
| P:41 | `human-typed`, `self-contained` | **updated** (census): WP-2 summary now names `form: self-contained` |
| P:43 | `--ac-file` | confirmed-consistent: resolution order |
| P:45 | `final audit` | confirmed-consistent: WP-4 summary ("the cap the ledger actually allowed") |
| P:79 | `final-audit` | confirmed-consistent: WP-3 table row |
| P:140 | `execution_rounds` | confirmed-consistent: block example |
| P:143, P:156, P:177 | `loosened` | confirmed-consistent: basis enum and definition |
| P:169 | `to 9`, `exits 1`, `limits-check` | updated (F-005): shared exit-code contract |
| P:178 | `to 9`, `exit 1` | updated (F-005): flag boundary row |
| P:181 | `form: self-contained`, `form: reply`, `exits 1`, `authorization/1`, `limits-check` | updated (F-001): `limits-check` boundary row |
| P:193 | `--ac-file` | confirmed-consistent: AC-7 |
| P:194 | `exit 1`, `--ac-file` | updated (F-005): AC-8 |
| P:195, P:196 | `exits 1` | updated (F-005): AC-9, AC-10 |
| P:199 | `form: self-contained`, `form: reply`, `self-contained`, `bare accept`, `verifies against the transcript`, `exits 1`, `authorization/1`, `execution_rounds`, `limits-check`, `loosened` | updated (F-001): AC-13 |
| P:201 | `audit_round_cap`, `exec_ledger_missing`, `rounds_allowed`, `execution_rounds`, `EXEC_REVIEW_MAX_ROUNDS`, `fallback`, `final audit`, `limits-check`, `loosened` | updated (F-002): AC-15 |
| P:202 | `limits-check` | confirmed-consistent: AC-16 (read-only) |
| P:203 | `regex`, `FIXED_CAP_INVENTORY` | updated (F-003): AC-17 ("not a regex") |
| P:209 | `FIXED_CAP_INVENTORY`, `check_ac17` | updated (F-003): inventory definition (single statement, PR-9) |
| P:225 | `human-typed`, `self-contained`, `form: reply`, `loosened` | **updated** (census): Spec Sufficiency row now names the form |
| P:236, P:240 | `final-audit`, `limits-check` | confirmed-consistent: Files Modified rows |
| P:244, P:246 | `--goal-anchor`, `--ac-file` | updated (F-004) |
| P:351 | `human-typed`, `bound authorization` | confirmed-consistent: D-2 records the human's decision verbatim; AC-13 implements it |
| P:382, P:384 | `limits-check`, `--ac-file` | confirmed-consistent: D-5 |
| P:404, P:406 | `fallback` | confirmed-consistent: D-7 (the `or` fallback in `tokens_spent`) |
| P:409, P:412, P:414, P:416 | `final audit`, `rounds_allowed`, `then 6`, `EXEC_REVIEW_MAX_ROUNDS`, `limits-check` | updated (F-002): D-8 |
| P:422 | `loosened` | confirmed-consistent: D-9 (off-Windows loosening refused) |
| T:44 | `rounds_allowed`, `fallback`, `final-audit`, `limits-check`, `loosened`, `audit_round_cap`, `exec_ledger_missing` | **updated** (census): row 4 said "with its fallbacks" and now names `audit_round_cap` and its order |
| T:46 | `FIXED_CAP_INVENTORY`, `check_ac17`, `rl-ac17` | updated (F-003): row 5a runs the oracle |
| T:47 | `rl-ac17` | confirmed-consistent: row 5b receipt name |
| T:71 | `EXEC_REVIEW_MAX_ROUNDS` | confirmed-consistent: H2-3b known-issues row |

Blast-radius census: 5 corrections, 35 values/variants swept, 39 sites found, 19 updated (3 of them caught by this census), 20 confirmed consistent. `task.md` re-lints clean (35 rows).

**Note on the Round 2 verdict document.** The Round 2 `final.json` (`changes_required`, `findings: []`) was refused by `review-verdict.schema.v2.json`, which requires a non-empty `findings` array for `changes_required`. So the dispatch wrapper did not record the round, and the ledger still shows 1/3. The PR-6 Verdict Rule ("return `changes_required` naming that alone ... not a severity-rated finding") and the v2 schema disagree. That is a framework defect, outside this plan.

## Round 2 (resubmission) — 2026-10-20

**Agent:** `gpt-6.1-sol` (dispatch status and `P:/.agent/model-registry.yaml:625` agree). **Loop:** `review-limits-parameters-plan-2026-10-20`. **Round:** 2. **Review mode:** plan. **Requested verbosity:** standard.

### Intent Anchor

"Make review round caps and token budgets setup choices in the repo, adopted by each plan and execution as tighten-only defaults, with loosening only through a verified human-typed offer."

**Intent achieved: yes, as an implementation plan. Verdict: approved with non-blocking notes.** The revised contracts close the three previously demonstrated delivery failures. This approves the unstarted plan; it does not claim the feature is implemented or authorize execution.

### Scope and PR-6 gate

Reviewed both complete target files, the corrections and census addendum, `check_ac17.py`, and the named live tools, workflows, templates and adoption documents. Also inspected the closeout validator, completion preflight, grouping format, policy template, diagram and dispatch/ledger identity. All numbered implementation rows remain unchecked; the new config, three proposed test files and project implementation handoff are absent. Existing changes to `run_parameters.py` and its two test files, and its `.orig` file, were present at this review's start. They are not this plan's implementation evidence and were not edited by this reviewer.

**PR-6 passes before substantive review.** The raw census receipt has 191 lines and exactly the supplied SHA-256, `4781c3f2be99da7fc39f904605376400ac2ec1bdc8f85a01a93e54542511f0a3`. It contains 35 value sweeps, each with an rg exit of 0 or 1, through the final `# rg exit 0`. All **40 unique file:line sites** match the current plan/task text byte-for-text after UTF-8 decoding, and all 40 have an `updated` or `confirmed-consistent` disposition in the correction log; no extra disposition site or undispositioned hit was found. The log's summary of 39 sites is a counting typo, not a missing disposition. The receipt contains the raw rg hits, including RTK diagnostics, rather than a head-truncated presentation.

The earlier unrecorded procedural refusal remains above as history. This is the resubmission of the same ledger round, so this append does not add another `## Recheck` heading. The historical frontmatter and earlier findings are preserved under the human's append-only instruction; this section and the round-2 v2 JSON express the current verdict. The historical frontmatter is not a newly generated approved-state receipt.

### Prior Pass Summary

| Finding | Recheck result | Verified correction |
|---|---|---|
| F-001 | **Fixed in plan** | Plan:41, 181, 199, 225 require `authorization/1`, `form: self-contained`, transcript verification and equality with the human's offered limits. AC-13 now pairs the assistant-offer/bare-reply refusal with positive human-typed numeric and `off` offers. Live `_verify_reference` at `run_parameters.py:1427–1455` obtains self-contained payloads from the typed human record, whereas reply form obtains them from the assistant. The distinction now appears across the summary, boundary and AC. |
| F-002 | **Fixed in plan** | Plan:201, 412–416 and task:44 specify one `audit_round_cap` resolver: existing execution ledger plus continuation grants; missing ledger with a task block refuses; only genuine blockless/no-ledger legacy tasks use repo/default fallback. Malformed and wrong-mode ledgers refuse. The task block is explicitly never an independent cap. The six AC-15 fixtures include the original unauthorized fallback, missing tighter-loop state, malformed/wrong-mode state and authorized round 7. Live `run_stage_validators` still has two fixed-cap arguments at 3746/3767, both scheduled for replacement; its `top` and `snapshot` arguments identify the real repo and temporary tree separately. |
| F-003 | **Fixed for the demonstrated failures; bounded residual below** | Plan:203, 209–217 and task:46 replace the old regex with an executable inventory oracle. Independent rerun exits 1 with 24 baseline and 24 live problems, including all three previously invisible cap forms. In-memory replacement of all inventory phrases plus source markers passes; restoring each of the 19 phrases individually refuses, 19/19. The previous illustrative round-7 sentence passes. This establishes bounded string coverage, not semantic completeness. |
| F-004 | **Fixed in plan** | Plan:244 and 246 explicitly schedule both missing required arguments, `--goal-anchor` and `--ac-file`, in the delegated and dispatch-skill `begin` examples. Those examples remain unchanged in the live tree, as expected before implementation. |
| F-005 | **Fixed in plan** | Plan:169, 178, 194–199 consistently distinguish ledger refusal 1, fail-closed 3 and usage 2; 9 is expressly the wrapper mapping. The raw census covers the old and new exit spellings in both carriers. |

### Findings

Both findings have **High confidence**, concern the **deliverable**, and are **non-blocking**. Neither alleges a new materially different failure of an already corrected control.

| # | Severity | Blocking | Kind | Finding | File:Line | Recommendation | Status |
|---|---|---|---|---|---|---|---|
| F-006 | Low | no | clerical | **The AC-17 inventory is bounded more narrowly than the remaining cap prose.** Removing all 19 listed phrases and adding file-level source markers makes `problems()` return `[]` while the lifecycle tables still say `3 non-approved rounds`, `6 non-approved rounds`, and `7th autonomous round`. File-wide marker presence also cannot establish that each replacement names its source, and retaining an inventory substring as an explicitly labeled default would still fail. These are residual predicate-coverage limits on the already corrected surface; under the Materiality Gate they do not reopen F-003. | `docs/execution/plans/2026-10-20-review-limits-parameters/implementation-plan.md:209`; `check_ac17.py:50`; live `core/.agent/docs/development-lifecycle.md:302`, `:397`, `:399` | Include the three neighboring table statements when making the already scheduled prose edit; manually verify each operative replacement's source. Describe this script as a bounded inventory check. | open |
| F-007 | Low | no | clerical | **AC-18's existing selftests are required but omitted from the explicit validation schedule.** Row 5c checks only block/version strings, and Verification §2 names only ledger/instantiate selftests. The intended commands are unambiguous and both tools exist; this is a scheduling correction, not a missing implementation deliverable. | `docs/execution/plans/2026-10-20-review-limits-parameters/implementation-plan.md:204`, `:298`; `task.md:48` | Add `python core/tools/lint_task_contract.py --selftest` and `python core/tools/validate_closeout_artifacts.py --selftest` to the existing AC-18 validation work, with the same receipt/exit handling. | open |

### Acceptance-Criterion and Entrypoint Recheck

These are falsifiability assessments of **planned tests**. No unwritten feature test is reported as passed.

| ACs | Recheck |
|---|---|
| AC-1–4 | Shipped-file equality can detect drift from the live five-mode maps. Nondefault flags/config and flag precedence can detect ignored setup choices; invalid-input tree hashes distinguish refusal-before-write. The installer has the claimed config/flag, verify and selftest extension points. Require actual integer types, excluding booleans, in JSON validation. |
| AC-5–9 | Nondefault repo cap 9 detects constant-only resolution; malformed-present versus absent tests prevent silent fallback. The strict six-key plan parser, computed basis, sibling equality and looser-flag refusals cover the stated repo → plan/task → flag boundary. Repo setup choices are intentionally mutable human configuration, not themselves restricted to shipped constants. Explicit flags only tighten the resolved value, including `off` ordering. |
| AC-10–11 | Huge measured usage with explicit `off`, numeric budget 1, and hand-edited 0/null refusal can distinguish disabled budgeting from numeric fallback. Keep measured usage even when budgeting is off. The implementation must also adapt the existing stop readout and formatted `begin`/`continue` messages, so an off loop still reports round/mechanism/scaffolding/instrument stops without numeric formatting errors. `continue --tokens` on off refuses; human `continue --rounds` remains the existing deliberate escalation path, not an autonomous flag loophole. |
| AC-12 | Compatibility is feasible because the existing allowlist does not require every key, and legacy grants without a `rounds` field intentionally buy one round. A current numeric ledger without `limits_source` evaluates successfully; the before/after fixture must preserve stored numeric budgets and grants rather than re-resolve repo defaults. This is a live pre-change observation, not post-change compatibility certification. |
| AC-13–14 | F-001's negative now distinguishes offer authorship. Disabled, off-Windows, manual, legacy, missing-key and mismatched-value refusals are explicit. Off-Windows refusal must be tested with an otherwise activated fixture: live `_gate` has no OS branch, while instantiate normally disables that install by removing components. `_ValueParser('3')` currently returns a string, so /2 support must change actual parsing as well as `_offer_types_ok`; the positive unquoted integer and negative quoted string jointly test that distinction. Preserve the /1 exact-key contract independently. |
| AC-15–16 | F-002's alternate unverified producer is removed. The ledger is now the required source for tasks carrying limits, and the defined missing/malformed/wrong-mode fixtures can refuse. Round 7 with and without a grant distinguishes continuation-aware from fixed/base-only caps. Resolve against the real repo and receipts store, not the audit snapshot. Hashes before/after both successful and refused `limits-check` runs test its read-only contract. |
| AC-17 | Independently demonstrated negative baseline, positive bounded replacement, all 19 individual phrase refusals and acceptance of the formerly false-failing illustrative sentence. The source check is file-level and the inventory omits adjacent tables: F-006. The Step-0 presence check still needs manual inspection of the actual resolution/write instructions. |
| AC-18–20 | Existing template versions and `{configured-cap}` cells match the proposed edit points. Blockless compatibility and ledger-derived source instructions are stated. Execute AC-18's named selftests (F-007). B5/B5b string checks and refcheck are runnable but require content review to establish the guidance, defaults and USD distinction. |
| AC-21 | Keeping USD behavior unchanged is the disclosed provisional D-1 choice. The credits suites and diff check can detect regressions; this review did not run them. |

**Hand-edited state:** the required 0/null validation closes sentinel smuggling; it does not authenticate arbitrary otherwise-valid ledger edits. `limits_source.repo` is an audit digest, not a signature. The live governance explicitly forbids editing a ledger to bypass a stop, and the plan does not promise tamper-proof storage. No such security property is inferred from AC-10, AC-12 or AC-15.

### D-1, D-5, D-8 and C2

- **D-1 is honest and sufficient for this planning review.** The plan quotes the ambiguity, states its provisional independent-USD choice, asks for confirmation, and retains the later human execution gate. The `Human-approved` source label at plan:341 should say pending interpretation/confirmation; the surrounding text already makes the uncertainty explicit. Approval does not decide what the human meant by `2. yes`.
- **D-5 is justified.** `_check_block` owns an exact run-parameters key set and `_within` compares its existing five values. A sibling block preserves repo defaults/tightening when that subsystem is disabled. The new loader and `limits-check` explicitly own the sibling boundary; the corrected final audit no longer assumes `_inherit` validates it.
- **D-8 is a disclosed, relevant correction.** It replaces the actual final-audit constant with the execution ledger's base plus continuation grants, closes the missing-ledger shortcut, and preserves a defined legacy path. The current task uses cap 6 explicitly under its bootstrap note at task:32–33; that is not a claim that every subsequent plan remains capped at 6.
- **C2 bases are substantively sufficient.** Grouping-line limits and per-plan limits for the other modes are outside the quoted plan/execution request; the grouping format exists at `core/.agent/workflows/session-grouping.md:114`. Other-mode repo defaults are a disclosed small extension of the shared resolver. Mechanism/scaffolding controls are separate from rounds/tokens. The policy template pins components, supporting the mutable-config distinction in D-6. USD scope remains explicitly provisional under D-1. The excluded SVG contains unlabeled `≤3 rounds`/`≤6 rounds`, so its claim to show defaults is imprecise; record that static-document limitation, without inventing a required diagram deliverable.

### Checklist Results

| Check | Result | Evidence / procedure |
|---|---|---|
| PR-1 Plan/task alignment | pass | WP-1–4 map to rows 1–5; corrected AC-13 and AC-15 map to row 4; AC-17 maps to executable row 5a. |
| PR-2 Unstarted | pass | No checked numbered implementation row; config, proposed test files and implementation handoff absent. |
| PR-3 Task contract | pass | Independent lint: 35 rows, 33 fully checked, two source-read exemptions; dependencies resolve and are acyclic. |
| PR-4 Validation realism | pass with notes | Existing executable paths and used flags/verbs verified; scheduled test files are prospective outputs. F-006/F-007 bound the remaining checks. |
| PR-5 Source basis | pass with note | Human request, D-2 and live constants support the feature; D-1 is disclosed pending confirmation despite its imprecise source label. |
| PR-6 Correction census | pass | Exact digest; 191 lines; 35 completed sweeps; 40/40 live sites dispositioned. |
| PR-7 Scope discipline | pass with notes | Real grouping/policy/credits/diagram sources inspected; no disguised unscheduled MEU deferral. |
| PR-8 Reachability/negative oracles | pass | Corrected typed-offer boundary and mandatory-ledger audit source have concrete refusal cases. AC-17's reported cases reproduced. |
| PR-9 Single statement | pass with note | Shared shapes, defaults and exit semantics still recur in boundaries/ACs/decisions; use the shared contract as canonical. No new materially different governing value found. |
| DR-1–8 Claims, references and evidence | pass within plan scope | Corrections are plan edits, not claimed completed feature work. Named tools exist; new config/tests/schema are scheduled. No implementation completion claim made. |

The executable-path sweep found `core/tools/{review_ledger,run_parameters,durable_evidence,issue_triage,lint_task_contract,validate_closeout_artifacts}.py`, `scripts/{instantiate,refcheck}.py`, and the plan-folder oracle on disk. `tools/validate_agent_files.py` correctly resolves under the plan's `Push-Location core`. New tests/config/offer schema are scheduled. Used lint, durable-evidence, issue-render and closeout options exist. The prose saying RTK is absent is stale; RTK is installed and was used for these commands.

### Durable Observations

```json
{"schema_version":"evidence.v1","check_id":"r2-resubmission-pr6","procedure":"Read the raw census as UTF-8, hash its bytes, extract unique implementation-plan.md/task.md file:line hits, compare every hit's full text against the current carrier line, and compare the hit set against all P:/T: sites in the Census Addendum disposition table. Inspect all sweep boundaries and final exit marker.","observer":"gpt-6.1-sol","exit_code":null,"result":"pass","scope":"PR-6 pre-verdict gate","phase":"manual","tested_state":"2026-10-20 round-2 resubmission","output":"sha256 4781c3f2be99da7fc39f904605376400ac2ec1bdc8f85a01a93e54542511f0a3; lines 191; sweep headers 35; unique hits 40; covered 40; undispositioned []; extra []; raw-vs-live mismatches []; all rg exits 0 or 1; last line # rg exit 0"}
```

```json
{"schema_version":"evidence.v1","check_id":"r2-resubmission-task-lint","command":"rtk proxy python -B -X utf8 core/tools/lint_task_contract.py --task docs/execution/plans/2026-10-20-review-limits-parameters/task.md","cwd":"P:/agentic-framework","exit_code":0,"result":"pass","scope":"unstarted task contract","phase":"static","tested_state":"round-2 resubmission","output":"OK: 35 row(s); 10-column table (with builder_model); 33 row(s) fully checked: backticked, exit-code re-raised, receipt under RECEIPTS_DIR; dependencies resolve and are acyclic; 2 row(s) exempt (view_file): H1-5, H2-1"}
```

```json
{"schema_version":"evidence.v1","check_id":"r2-resubmission-ac17-live-negative","command":"rtk proxy python -B -X utf8 docs/execution/plans/2026-10-20-review-limits-parameters/check_ac17.py","cwd":"P:/agentic-framework","exit_code":1,"result":"pass","scope":"expected negative baseline before implementation","phase":"static","tested_state":"live five workflow/doc files and pinned baseline d698342","output":"self-check: 24 problems at d698342 (oracle can fail)\nAC-17 FAIL: 24 problems in the working tree","evidence":"Diagnostics include round cap (3), round cap (6), execution = 6, all other inventory phrases and five missing file-level source markers. Expected refusal, not a failing implemented feature test."}
```

```json
{"schema_version":"evidence.v1","check_id":"r2-resubmission-ac17-in-memory","procedure":"Import the actual check_ac17.py with bytecode disabled. Read its five inputs into memory. Replace each listed phrase and add a review_limits source marker to each file; invoke its real problems function. Restore each of the 19 phrases separately and invoke problems again. Append the prior illustrative round-7 sentence to the cleaned inputs. Inspect surviving non-approved-round and seventh-round table lines. No repository file is changed.","observer":"gpt-6.1-sol","exit_code":null,"result":"pass","scope":"bounded oracle regression cases and residual coverage","phase":"manual","tested_state":"current oracle and live input texts","output":"all_inventory_replaced []; individual_preserved_phrase_refusals 19 of 19; illustrative_round7 []; residual table statements at development-lifecycle.md:302,397,399 remain (F-006)"}
```

```json
{"schema_version":"evidence.v1","check_id":"r2-resubmission-legacy-observation","procedure":"Read the registered loop's current numeric ledger without writing it; call live rounds_allowed, tokens_spent and stops. In a separate in-memory copy replace grants with one legacy grant lacking rounds, and call rounds_allowed. Inspect the loader's optional-key allowlist and the parser's unquoted integer behavior.","observer":"gpt-6.1-sol","exit_code":null,"result":"pass","scope":"pre-change legacy extension points only","phase":"manual","tested_state":"live review-ledger.v1 numeric loop without limits_source","output":"limits_source absent True; rounds_allowed 3; with one legacy grant lacking rounds 4; tokens_spent (8657216, 8657216, 31500000); active_stops []; _ValueParser('3').parse() returns string '3'"}
```

### Verdict and Follow-up

`approved` — F-001–F-005 are corrected in the unstarted plan. No blocking finding remains. F-006/F-007 are non-blocking correction notes and should be handled in the already scheduled documentation/validation work. D-1 remains pending human interpretation; this verdict does not supply that answer. No product suite, prospective feature selftest or implementation test was run.

Only this rolling review handoff was edited in the repository. No plan, product file, tool or test was changed; no git commit was created. The final v2 JSON records the current verdict and surviving non-blocking findings. It takes precedence over the workflow's stale v1 empty-findings wording. The human's JSON-only output requirement also takes precedence over a separate final-chat timestamp; the timestamp skill output is embedded here.

Final `rtk git status --short` exited 0. Concurrent workspace activity has staged the three pre-existing tool/test changes and removed the `.orig` listing since the initial status; this reviewer performed neither action. The review handoff and plan directory remain untracked.

🕐 Completed: 2026-10-20 15:10 (EDT)

## Post-Approval Correction Notes Applied (planner, 2026-10-20)

Both non-blocking Round 2 notes were applied. Each one tightens the plan and loosens no check.

- **F-006:** `FIXED_CAP_INVENTORY` and `check_ac17.py` add `3 non-approved rounds`, `6 non-approved rounds` and `7th autonomous round` (`development-lifecycle.md:302,397,399`). The self-check now finds 27 problems at `d698342`. The plan now calls the script a bounded inventory check and has the WP-4 editor read each replaced statement in place.
- **F-007:** new task row 5c2 runs `lint_task_contract.py --selftest`, then `validate_closeout_artifacts.py --selftest`, with the exit code preserved and receipts written. Both pass on the current tree. `task.md` lints clean (36 rows).

## Corrections Applied — D-1 Amendment (planner, 2026-10-20, before round 3)

**Why the approved plan changed.** After the round-2 approval, the human resolved D-1 in chat: "1. limit should be off as well". So `token_budgets: "off"` now also lifts the USD caps on scheduled credits runs. The earlier plan default kept them independent. That default is reversed, and the plan gains WP-5 and AC-21–AC-27. The old AC-21 ("no credits tool is touched") and task row 5f are removed. The registered goal anchor is unchanged. The credits work is in scope only because the human answered D-1.

**What changed.**

| Area | Change |
|---|---|
| Goal | "four parts" becomes "five parts". Part 5: credits USD caps follow the switch. The "separate control" sentence is removed. |
| Work packages | WP-4 covers AC-17–AC-20. New WP-5 covers AC-21–AC-27 and depends on WP-2, because it reads the repo file through `load_repo_limits`. |
| User Review Required | Item 2: D-1 resolved, with what still bounds an uncapped run. |
| Shared contract | New "Credits manifests under `token_budgets: "off"`" bullets: the file is read only when a cap is omitted; caps are optional; uncapped admission; the refusal codes; plan-level `execution_tokens: off` has no credits effect. |
| Boundary Inventory | New row for the three manifest caps. |
| ACs | AC-19 now says that "off" lifts the credits USD caps. The old AC-21 is replaced by AC-21 (register), AC-22 (admission rooms), AC-23 (`caps_required` re-check), AC-24 (0 exposure), AC-25 (chain room `None`), AC-26 (schema plus `-MaxBudgetUsd 0`, Pester) and AC-27 (SKILL text plus credits regression). |
| Spec Sufficiency, Out of Scope | USD caps row resolved. Out of Scope now lists the manual runner's $2 default and plan-level token "off" lifting credits caps. |
| Files Modified | `credits_state.py`, `credits-run.v1.json`, `Start-CreditsRun.ps1`, claude-credits `SKILL.md`, the new `test_credits_uncapped.py`, and the two Pester files. |
| Verification | `credits_state.py` added to static (four files). `test_credits_uncapped.py` added to targeted. Pester now runs under `pwsh`, with the exit code taken from `FailedCount`. |
| Decisions | D-1 is `chosen: Yes`, citing USER_EXPLICIT "1. limit should be off as well". The D-1 brief is rewritten. New D-11 (present caps still bind; re-check at each admission), D-12 (uncapped exposure 0) and D-13 (read through `review_ledger.load_repo_limits`). |
| task.md | Estimate updated. Row 5d now also greps `credits`. Row 5f removed, and row 6 depends on 5e. New rows 7 (WP-5a, credits_state plus pytest), 7a (WP-5b, schema, launcher and Pester), 7b (WP-5c, SKILL text) and 7c (credits pytest plus full Pester). H1-1 depends on 7c. H2-3c wording updated. `lint_task_contract.py`: OK, 39 rows. |

**Live facts the amendment relies on** (read at e667fb6):
- `credits_state.py:2252-2259`: rooms, `min`, `FLOOR_USD`.
- `:2262-2272`: rejection routing.
- `:2416-2421`: the exposure equals the reservation.
- `:2814`: `chain_room`.
- `:2960`: `ready`.
- `:1757`, `:1766`, `:1835-1836`: cap validation.
- `:1924-1931`: whole-block chain equality.
- `:284-285`: nullable cap columns.
- `Start-CreditsRun.ps1:521`, `:588`: the reservation is passed as `-MaxBudgetUsd`.
- `Invoke-ClaudeCredits.ps1:78`: default 2. `:272`: 0 means no cap.
- `CreditsRun.psm1:34`: `credits_state.py` runs from `<repo>/tools`.

**Census (Step 5c).** Receipt: `C:/Temp/agentic-framework/receipts/census-rl-r3/census-review-limits-r3.txt` (sha256 `8ad84c8717fc8c7f66bccc13632126a952fcd411966e656aa71b9f712ded75e2`). It holds a raw `rg -F -n` sweep of both plan files for every changed value, with each value's rg exit code. P = implementation-plan.md, T = task.md.

| Value | Hits | Disposition |
|---|---|---|
| Removed: `four parts`, `three files`, `three new test`, `5f`, `ending confirmation`, `separate control`, `AC-17–AC-21`, `about 20 files` | none (rg exit 1) | updated: no stale site remains |
| `five parts` | P32 | updated |
| `four new test` | P537 | updated (validation stage contract) |
| `AC-17–AC-20` | P81, T45 | P81 updated; T45 confirmed-consistent (row 5 already said AC-17–AC-20) |
| `AC-21`, `AC-27` | P83, P233, P239, P259, P283, P286, P287, P352, P364, T53, T55, T56 | updated (new WP-5 text) |
| `D-1` (all forms) | P51, P99, P231, P233, P234, P237, P238, P259, P300, P301, P508 | updated |
| `D-11`, `D-12`, `D-13` | P103, P182, P186, P234–P236, P259, P476, P486, P496, P512 | updated (new) |
| `USD` | P48, P49, P83, P99, P100, P188, P231, P234, P237, P259, P376, P379, P508, P511, P524–P526, T50 | updated |
| `credits` | P403 (D-3), P433 (D-6), P214 (AC-2 `--credits-start-policy`) | confirmed-consistent (`.agent/credits/config.json` precedent, unaffected) |
| `credits` | every other hit (P48 … P524, T13, T50, T53–T56, T76) | updated |
| `MaxBudgetUsd`, `max-budget-usd` | P50, P101, P189, P190, P238, P285, P300, P379, P381, P512, P517, T54 | updated |
| `independent` | P525 | updated (the rejected option in the D-1 brief) |
| `independent` | T66, T67 | confirmed-consistent ("independent reviewer"; unrelated) |
| `Invoke-Pester` | P355, T54, T56 | updated (all run under `pwsh` with `-PassThru` and `FailedCount`) |
| `WP-5`, `caps_required`, `uncapped`, `review_limits_invalid` | all hits | updated (new) |

## Recheck (2026-10-20) — Round 3

**Review mode:** `plan` · **Agent:** `gpt-6.1-sol` · **Verbosity:** `standard` · **Verdict:** `changes_required` · **Intent achieved:** `partial`

### Intent Anchor

"Make review round caps and token budgets setup choices in the repo, adopted by each plan and execution as tighten-only defaults, with loosening only through a verified human-typed offer."

WP-1–WP-4 still satisfy the previously approved planning contract. The human's D-1 answer legitimately adds optional scheduled-credits caps, but the amendment's Pester gate can report success while its required acceptance assertions never run.

### Scope and PR-6 Gate

Reviewed both unstarted plan carriers and the D-1 correction log, then traced the named credits Python, schema, PowerShell launch/registration paths and existing fixtures. Baseline HEAD: `e667fb689980ce47d32c0e6fd154779f3c23c9cc`. All 39 task rows remain unchecked; the proposed config, four test files and implementation handoff are scheduled outputs, not completed implementation. The live registry at `P:/.agent/model-registry.yaml:625` binds the independent Codex reviewer to `gpt-6.1-sol`; the ledger producer is `claude-opus-coordinator`.

**PR-6 passed before substantive recheck.** The named receipt has the exact supplied SHA-256, 218 lines, 29 sweep headers with 29 exit markers, and 82 unique plan/task `file:line` hits. Every hit's full text matches the current carrier line. Every hit maps to `updated` or `confirmed-consistent` in the amendment's disposition table, including the explicitly grouped “all hits” and “every other hit” categories; these refer to the complete raw inventory, rather than an unsupported count. No truncated sweep or missing disposition was found. The final marker is `# rg exit 1`, correctly recording the absent `about 20 files` phrase. Two non-ASCII sweep labels were decoded with replacement characters in the supplied receipt; the separate raw hits and the exact-value disposition table make their meaning unambiguous.

### Findings

Both findings have **High confidence**. Plan/task line references below resolve under `docs/execution/plans/2026-10-20-review-limits-parameters/`.

| # | Severity | Blocking | Kind | Finding | File:Line | Recommendation | Status |
|---|---|---|---|---|---|---|---|
| F-008 | High | yes | control-defeat | **The new Pester gate false-passes a discovery failure.** `mechanism: task-row-completion-predicate`. All three commands derive success solely from `$r.FailedCount`. On installed Pester 5.7.1, a container that throws during discovery returns `Result=Failed`, `FailedContainersCount=1`, `FailedCount=0`; the exact planned exit expression returns 0. An isolated two-container probe also passed one unaffected test while the required container never discovered its assertions, yet still exited 0. Thus the AC-26 optional-cap/uncapped-argv acceptance work and AC-27 regression requirement can be treated as green with those assertions materially absent. This is a demonstrated defect in the newly added Pester surface, not a deeper mutation of the corrected AC-17 oracle. **Violated contract: AC-27** (also affects AC-26). | `implementation-plan.md:355`; `task.md:54`, `:56` | Make a failed Pester result, discovery/container error, or invocation failure produce a nonzero child exit; for example require a non-null result with `Result` equal to `Passed`, with terminating invocation errors. Prove the wrapper fails for both an assertion failure and a discovery failure while an unaffected container passes. Update the three occurrences as one gate contract. | open |
| F-009 | Low | no | clerical | **The loop's registered AC inventory predates the amendment.** Subject: `review-scaffolding`. The live ledger contains only AC-1–AC-21, although the reviewed plan now defines AC-1–AC-27. `cmd_record` rejects any blocking citation outside that registered set, so recording F-008's accurate AC-27 citation will currently be refused. This administrative mismatch does not change the substantive verdict and is not a reason for another review round. | `core/tools/review_ledger.py:844`; registered loop `review-limits-parameters-plan-2026-10-20`, field `ac_ids` | Have the loop owner reconcile the amended contract registration before recording this verdict, preserving the existing two rounds, history and cap of 3. Do not reset/reopen the loop or relabel the blocker to an unrelated AC. | open |

### Prior Pass Summary

| Finding / decision | Recheck result |
|---|---|
| F-001–F-005 | Remain fixed in the plan: human-typed self-contained loosening, mandatory new-loop execution ledger, bounded cap inventory, complete begin examples and corrected exit contracts. |
| F-006 | Fixed: the plan and `check_ac17.py` include the three lifecycle-table phrases and explicitly require reading replacements in place. |
| F-007 | Fixed: task row 5c2 schedules both existing selftests and preserves the first failing status. This review did not execute those prospective implementation checks. |
| D-1 | Resolved by the supplied human message, “1. limit should be off as well.” The earlier independent-USD recommendation and old AC-21/row 5f are removed. |

### Substantive Falsification Audit

These are source-grounded assessments of the proposed implementation and tests, not claims that unwritten feature tests passed.

| Surface | Assessment |
|---|---|
| AC-21: optional-cap authority | `load_manifest` currently requires positive segment/run caps at `credits_state.py:1835`; `parse_chain` requires the exact chain block at `:1754`. The plan explicitly changes both, keeps all other chain keys required, distinguishes omission from a present invalid value, and makes malformed/absent/on repo cases refuse. `_positive` already rejects booleans, nonfinite numbers, zero and null. A missing chain block is not an omitted cap in an existing chain block. Positive optional-cap registration and negative on/absent/malformed cases can fail against the named producer. |
| AC-22: partial caps and floor | The current rooms/min/floor producer is `verb_admit:2251–2259`. Building rooms only from present limits permits the all-omitted case without weakening any present cap. The proposed negatives distinguish no rooms, only run room 3, and only segment room 40. The floor remains strict `< 5`; the unchanged exposure/floor test at `test_credits_state.py:1279` already asserts admission at exactly 5 and refusal below it. A run with any present room is capped, regardless of the repo switch. |
| AC-23: switch-back reachability | `Start-CreditsRun.ps1:512` calls the real `admit` verb on accepted first starts and resumes. The re-read belongs there, against the stored manifest's project root, not only in registration or tests. First-start `caps_required` and malformed-config rejection must enter the failed/start_refused branch: merely assigning a new reason to current `:2268` would fall through to waiting. Resume must reject the request/attempt, remain stopped and emit resume_refused. AC-23 explicitly requires these observable states/notices; its registered-then-on/deleted and stopped-resume tests can falsify a registration-only check. Capped manifests must avoid the new file read, preserving fixtures whose project roots are deliberately nonexistent. |
| AC-24 / D-12: exposure 0 | `finalize_segment:2411–2430` already records an untrusted segment's reservation as both exposure amounts and leaves cost_known 0. With the specified zero reservation this yields a real zero exposure row and satisfies finalized_without_cost (`:1579` requires the row, not a positive amount). `run_spend` reads exposure amounts and reservations; it does not interpret zero as an unlimited-budget sentinel. Those amounts feed capped run/chain rooms, so D-12's “no cap reads the exposure” applies specifically to a genuinely uncapped segment, whose immutable manifest has no such room. Present-cap segments continue to reserve/expose their actual limit. No new accounting invariant contradiction was found. |
| AC-25: None and chain equality | `chain_room:2814`, both `parse_chain` callers at admission/candidates, and `verb_chain_candidates:2960` are named change points. None must be skipped when adding admission rooms and must mean no floor in candidate readiness. Existing `check_chain_block:1924–1930` compares whole blocks, including cap omission: it prevents a capped block joining an uncapped chain and preserves the existing conservative minimum for any stored caps. Ready despite large spend, capped room below floor and chain_conflict are meaningful contrasting observables. |
| AC-26: actual argv and schema | `Start-CreditsRun.ps1:588` already passes an explicit MaxBudgetUsd. Passing 0 through this parameter prevents the manual wrapper's omitted-value default of 2 (`Invoke-ClaudeCredits.ps1:78`). That wrapper only binds the dispatch argument when it is positive (`:272`); dispatch's `:553` rejects a bound nonpositive value and `:931` adds the CLI flag only when bound. Therefore explicit 0 at the credits wrapper yields no CLI --max-budget-usd without changing dispatch. Verify a launched child and captured argv as well as flag absence. The registration schema walker checks existing keys recursively and enforces exclusiveMinimum; removing only the three required-list entries preserves positive present caps, named properties and additionalProperties false. Existing schema tests assert properties/closed objects, not mandatory cap presence. The new acceptance assertions are meaningful, but F-008 defeats their scheduled gate. |
| AC-27: fixtures, scope and tests | Existing credits fixtures carry segment/run caps and omit the optional whole chain; capped chain fixtures carry their cap. Lazy loading only for an actually omitted applicable cap preserves these unchanged fixtures without requiring a real fixture project root. The manual runner default remains untouched. The skill's Schedule section is an appropriate disclosure surface. Full credits pytest plus every Pester suite is scheduled; no product suite was run in this plan review. F-008 prevents trusting its current Pester exit as proof. |
| D-13: import/layout | CreditsRun.psm1:33–34 invokes the adopted tools/credits_state.py beside review_ledger.py. The fixture CLI also executes that script directly, so its tools directory is available for the lazy sibling import. review_ledger imports only stdlib modules, constructs constants/path values, and protects main with its __name__ guard; it does not create a ledger at import. WP-2 owns the new loader. Translate its malformed-file exception to credits review_limits_invalid and feed the admission rejection routing above. No dependency cycle or required third-party dependency was found. |
| WP-1–WP-4 and scope | Existing approval stands. Source comparison from d698342 to e667fb6 finds changes only in run_parameters.py among the supplied earlier surfaces: typed-human predicates now delegate to credits_state and text extraction accepts text-only blocks; the self-contained-versus-reply distinction remains. EXEC_REVIEW_MAX_ROUNDS is at 3425 with uses at 3746/3767, matching AC-15. D-1 adds scheduled credits behavior requested by the human, preserves present caps, leaves plan-level review-token choices scoped to their loops and leaves the manual runner's default alone. D-11–D-13 are disclosed implementation choices; their AC source labels saying Human-approved are broader than the actual autonomous decisions, but the decision log unambiguously records their origin. No new scope blocker or conflicting governing limit was found. |

### Checklist Results

| Check | Result | Observation |
|---|---|---|
| PR-1 / PR-2 / PR-3 | pass | WP-5 maps to rows 7–7c after WP-4, depends on WP-2, and H1 waits for it. All 39 rows unchecked; lint checks 37 and exempts two source reads; dependencies acyclic. |
| PR-4 / PR-8 | fail | F-008 demonstrates a failed container with missing acceptance assertions and a successful planned exit. Other producer/caller/negative-oracle paths are assessed above. |
| PR-5 / PR-7 | pass with notes | D-1 is explicit human authority; no unscheduled MEU deferral. Autonomous implementation decisions are disclosed, despite loose Human-approved labels on some ACs. Existing static-diagram/default and mutable-config scope notes remain unchanged. |
| PR-6 | pass | Exact digest, full sweep boundaries, 82 live hits, complete dispositions. |
| PR-9 | pass with notes | Shared contract governs repeated off/required-cap/room statements. No incompatible governing value found. Treat the three Pester expressions as one corrected gate. |
| DR-1–3 / DR-5–8 | pass within plan scope | Amendment matches live plan text and prospective output inventory; no implementation-complete claim. Named commands exist or are scheduled creations. |
| DR-4 | fail | Pester discovery errors are not covered by the new FailedCount-only predicate. |

### Durable Observations

```json
{"schema_version":"evidence.v1","check_id":"r3-pr6-census","command":null,"procedure":"Hash the named census bytes, inspect all 29 sweep boundaries and exits, extract its unique plan/task file:line hits, compare each full raw hit to the current carrier line, and map the hit inventory to the D-1 correction log dispositions before examining corrected content.","observer":"gpt-6.1-sol","exit_code":null,"result":"pass","phase":"manual","scope":"PR-6 pre-verdict gate","tested_state":"HEAD e667fb689980ce47d32c0e6fd154779f3c23c9cc and untracked D-1-amended plan","output":"sha256 8ad84c8717fc8c7f66bccc13632126a952fcd411966e656aa71b9f712ded75e2; 218 lines; 29 sweeps; 29 exit markers; 82 unique hits; raw-vs-live mismatches []; all hits dispositioned; final # rg exit 1"}
```

```json
{"schema_version":"evidence.v1","check_id":"r3-task-lint","command":"rtk proxy python -B -X utf8 core/tools/lint_task_contract.py --task docs/execution/plans/2026-10-20-review-limits-parameters/task.md *> C:/Temp/agentic-framework/receipts/rl-r3-task-lint.txt; $code=$LASTEXITCODE; rtk read C:/Temp/agentic-framework/receipts/rl-r3-task-lint.txt; exit $code","exit_code":0,"result":"pass","phase":"static","scope":"unstarted task contract","tested_state":"D-1 amendment at review time","output":"OK: 39 row(s); 10-column table (with builder_model); 37 row(s) fully checked: backticked, exit-code re-raised, receipt under RECEIPTS_DIR; dependencies resolve and are acyclic; 2 row(s) exempt (view_file): H1-5, H2-1"}
```

```json
{"schema_version":"evidence.v1","check_id":"r3-pester-discovery-false-pass","command":"rtk proxy pwsh -NoProfile -Command '$container = New-PesterContainer -ScriptBlock { throw \"R3 deliberate discovery failure\" }; $r = Invoke-Pester -Container $container -Output Minimal -PassThru; Write-Output (\"RESULT={0}; FailedCount={1}; FailedContainersCount={2}; TotalCount={3}; PlannedExit={4}\" -f $r.Result,$r.FailedCount,$r.FailedContainersCount,$r.TotalCount,[int]($r.FailedCount -gt 0)); exit [int]($r.FailedCount -gt 0)' *> C:/Temp/agentic-framework/receipts/rl-r3-pester-discovery.txt; $code=$LASTEXITCODE; rtk read C:/Temp/agentic-framework/receipts/rl-r3-pester-discovery.txt; exit $code","exit_code":0,"result":"fail","phase":"targeted","scope":"new Pester completion predicate under a deliberate discovery failure","tested_state":"installed Pester 5.7.1; in-memory container; no repository test edited","output":"Discovery in <ScriptBlock> failed: R3 deliberate discovery failure; Discovery found 0 tests; Container failed: 1; RESULT=Failed; FailedCount=0; FailedContainersCount=1; TotalCount=0; PlannedExit=0"}
```

```json
{"schema_version":"evidence.v1","check_id":"r3-pester-mixed-false-pass","command":null,"procedure":"Execute two New-PesterContainer ScriptBlocks: one Describe/It asserting 1 equals 1, and one throwing during discovery. Invoke Pester with Run.PassThru true and TestRegistry/TestDrive disabled to isolate the result accounting from sandbox registry permissions. Print result counters, the plan's FailedCount-only exit, and a Result-not-Passed exit; return the plan's exit. A preceding default-configuration mixed probe failed because the sandbox denied Pester TestRegistry access (FailedCount 1); it was not used as false-pass evidence.","observer":"gpt-6.1-sol","exit_code":null,"result":"fail","phase":"manual","scope":"required container absent while unaffected assertions run","tested_state":"installed Pester 5.7.1; two in-memory containers; no product suite","output":"RESULT=Failed; PassedCount=1; FailedCount=0; FailedContainersCount=1; TotalCount=1; PlannedExit=0; ResultExit=1; actual child exit 0"}
```

```json
{"schema_version":"evidence.v1","check_id":"r3-ledger-registration","command":null,"procedure":"Read the registered loop JSON without mutation and inspect review_ledger.cmd_record's blocking-citation check. Compare the registered AC IDs to the amended plan's AC table.","observer":"gpt-6.1-sol","exit_code":null,"result":"fail","phase":"manual","scope":"recordability of the amended contract; non-blocking review scaffolding","tested_state":"existing loop with round_budget 3 and two recorded rounds","output":"registered ac_ids AC-1 through AC-21; amended plan AC-1 through AC-27; record rejects a blocking violates value outside the registered set at review_ledger.py:844; no record/reset/amend operation performed"}
```

### Verdict, Follow-up and Limits

`changes_required` — one High blocking finding, F-008 (AC-27), in the newly amended Pester gate. F-009 is non-blocking review scaffolding. Correct the gate once across its three uses and preserve a discovery-failure negative receipt. The earlier WP-1–WP-4 approval remains substantively valid. The human's execution go-ahead is acknowledged; this review does not begin execution.

This is round **3 of 3**. Do not autonomously start corrections, another review round, or reset the ledger. The loop owner must handle any further action and the stale AC registration while retaining history and the cap. No further human product decision is needed on D-1. Residual risk: this is a source/plan review, not execution evidence; unwritten optional-cap tests and full suites still need to run during authorized implementation.

Pre-Edit Guard: the sole repository edit target is the canonical rolling review path derived from the supplied plan folder. Earlier sections and frontmatter are preserved; the newest section/final JSON carry the round-3 verdict. No plan, tool, product or test file was edited and no commit was created. The timestamp skill was used for this handoff; the required final JSON takes precedence over a separate final-chat timestamp.

Final verification: the round-3 JSON passes `jsonschema.validate` against the repository's `review-verdict.schema.v2.json` (exit 0, one blocking finding). Both plan-file SHA-256 values match the pre-edit capture. Final Git status still lists only the pre-existing untracked review handoff and plan folder. Schema validity does not resolve F-009's separate ledger-registration refusal; this reviewer did not attempt to record the verdict.

🕐 Completed: 2026-10-20 15:52 (EDT)

## Corrections Applied — Round 3 F-008 and F-009 (planner, 2026-10-20, after round 3)

**Ledger state, disclosed first.** The round-3 verdict above (`changes_required`, F-008 blocking, F-009 non-blocking) is **not recorded**. `review_ledger.py record` refused it, because F-008 cites `AC-27` and the loop registered only AC-1–AC-21 at `begin` (`review_ledger.py:844`). The dispatch log ends `FAIL: verdict-not-recorded … no round was consumed`. The ledger therefore still reads `rounds 2/3`, `NEXT ROUND: permitted`. That count is an artifact of the refusal, not of the review: round 3 ran in full and its verdict is substantive. The ledger was not hand-edited, reset or reopened. How the loop proceeds from here is the human's decision (see "Next step" below).

**Framework defect (for the known-issues register).** A loop's `ac_ids` are fixed at `begin`, and no verb re-registers them. A plan amendment that adds ACs after `begin` therefore produces blocking findings that `record` must refuse, and the loop cannot record its own review of the amendment.

**F-009: AC set matches the registered set.** AC-21–AC-27 are folded into one row, AC-21, with parts (a)–(g). The text of each part is the old row's text, unchanged except as listed below. Every reference is remapped: AC-21–AC-27 → AC-21 (a)–(g); AC-21–AC-25 → AC-21 (a)–(e); AC-23 → AC-21 (c); AC-26 → AC-21 (f); AC-27 → AC-21 (g). The plan's AC set is now AC-1–AC-21, equal to the registered `ac_ids`. Under that mapping, F-008 violates AC-21 (g), and also affects AC-21 (f).

**F-008: the Pester gate cannot false-pass, and the credits gates compare with a baseline.**

| Area | Change |
|---|---|
| `run_pester.ps1` (new, plan folder) | Counts each container in `FailedContainers` (a discovery or setup-block failure) and each failed test alike, as ids `container:<file>` and the test's `ExpandedPath`. Without `-Baseline`, it passes only when `Result` is `Passed`, nothing failed and at least one test passed. With `-Baseline`, it passes only when at least one test passed and every id is in the baseline list. `-FailuresOut` writes the list. Before the real run, it self-checks on temporary probe files: all passing → pass; an assertion failure → refuse; **a discovery failure beside a passing container → refuse** (the round-3 probe case); a baseline listing the assertion failure → pass; a new discovery failure against that baseline → refuse. |
| `new_failures.py` (new, plan folder) | Compares two pytest receipts written with `-rfE`. It passes only when the later receipt has a summary line with at least one passed test, and no `FAILED`/`ERROR` id that the baseline lacks. Self-check: same failure, fewer failures, the bare `-q` summary form → pass; a new failure, a collection error, a crashed run → refuse. |
| `stage_core.py` (new, plan folder) | Copies the working tree's `core/` to `C:/Temp/agentic-framework/rl-stage`, fills it with `instantiate.py`, and runs `--verify`. The credits suites read filled-in placeholders such as `{{RECEIPTS_DIR}}`, so they fail in the raw template; they now run from the stage. |
| Plan §3 | The three FailedCount-only expressions are replaced by one staged credits pytest compared through `new_failures.py`, and one `run_pester.ps1 -Baseline` run on every staged Pester suite. The full pytest gains `-rfE` and a `new_failures.py` comparison. The prose explains all three helpers. |
| Plan preamble | Every command runs with `$env:AGENT_MODEL_REGISTRY_HOME = 'P:/.agent'` (`core/.agent/INSTANTIATE.md` §1). Without it, the wrapper Pester suites fail `registry_not_found`, and the baseline would excuse failures that only the environment causes. |
| Baseline (plan bullet, task row 0) | Row 0 runs the full pytest, the staged credits pytest and the staged Pester suites on the unchanged tree, and keeps `rl-full-pytest-baseline.txt`, `rl-credits-stage-baseline.txt`, `rl-pester-baseline.txt` and `rl-pester-baseline-failures.txt`. These runs may fail; row 0 checks that each receipt is complete. It records `RECEIPTS_DIR` and `AGENT_MODEL_REGISTRY_HOME` with the input identity. |
| AC-21 (f), (g) | (g) now reads: "Run in the instantiated stage, every credits pytest and Pester suite has no failure that its row-0 baseline lacks, the new and changed tests pass, and the existing fixtures are unchanged." Its negative check: "`new_failures.py` passes … and `run_pester.ps1 -Baseline` passes … A gate that is fed a new failure, a discovery failure or a crashed run refuses it (each script's self-check)." In (f), the capped test at `Start-CreditsRun.Tests.ps1:283` "passes in the stage, where it also passes at baseline". |
| Task rows 7a, 7c, H1-2 | 7a: `stage_core.py`, then `run_pester.ps1 -Baseline` on the two changed Pester files. 7c: `stage_core.py`, the staged credits pytest through `new_failures.py`, then `run_pester.ps1 -Baseline` on every staged suite. H1-2: full pytest with `-rfE` through `new_failures.py`. Receipt names follow the merge (`rl-ac21a-e`, `rl-ac21f`, `rl-ac21g-*`). |
| Validation stage contract | Fresh full names the staged gates; Blocking names the two comparison tools as the proof that a failure pre-exists. |

Why a baseline and not "green": on this machine, before any change, the staged credits pytest gives `17 failed, 459 passed, 50 skipped` (receipt `C:\Users\Mat\AppData\Local\Temp\claude\p--agentic-framework\2469ffc9-4b7e-4176-9e1c-855085be1702\tasks\bqdjup6fq.output`). The failures come from `ModuleNotFoundError: No module named 'psutil'` in `run_parameters` paths, for example `test_credits_phases.py::test_d20_b_headless_binding_refuses_interactive_acts`. "Every suite stays green" could not be met by any change. Requiring "no failure the baseline lacks" can be.

**Staged Pester baseline (probe, before any change).** With `AGENT_MODEL_REGISTRY_HOME=P:/.agent`, `run_pester.ps1` on every suite under the stage's `tools/tests` printed its self-check line, then `Pester gate PASS: Result=Passed Passed=324 Failed=0 FailedContainers=0 Skipped=0 Baseline=none Unexcused=0`, and the failure list it wrote is empty (receipt `C:/Temp/agentic-framework/receipts/rl-stage/pester-probe2.txt`, sha256 `3eb052c20e904bbe03c3303938eadca1b43375659dfbf8a57c9b86e377bc3400`). So the Pester baseline is clean, and with `-Baseline` any failure, the round-3 discovery case included, blocks. An earlier probe without the registry variable failed many wrapper tests with `registry_not_found`; it is discarded, and that is why the preamble now sets the variable. The probe also caught a defect in the first draft of the gate: it read every container whose `Result` was `Failed` as a container failure, which counts a failing test twice and stops a baseline from excusing it. The self-check refused that draft (`baseline assertion failure gave False`), and the gate now reads `FailedContainers`.

**Lint.** `lint_task_contract.py --task …/task.md`: `OK: 39 row(s); … 37 row(s) fully checked …; 2 row(s) exempt (view_file): H1-5, H2-1`. The linter refused the first draft of rows 0 and H1-2, because the exit status was not captured right after each redirected command. Both rows now capture it.

**Census (Step 5c).** Receipt: `C:/Temp/agentic-framework/receipts/census-rl-r3b/census-review-limits-r3b.txt` (sha256 `e0f5930116a2ae1cdfe0465df5f037d56bee90ceebd9882b097c20af0e35cc99`). It was taken before the AC-21 (f) wording edit, so its hit on implementation-plan.md:233 shows the earlier (f) clause. It has 19 sweeps (`rg -F -n` over both plan files): `AC-22`…`AC-27`, `AC-21 (`, `Invoke-Pester`, `FailedCount`, `stays green`, `rl-ac2`, `-rfE`, `new_failures`, `run_pester`, `stage_core`, `AGENT_MODEL_REGISTRY_HOME`, `baseline`, `Pester`, `rl-stage`. Of those, 7 end `# rg exit 1`: `AC-22`–`AC-27` (the merge is complete) and `Invoke-Pester` (the old gate is gone). There are 45 unique `file:line` hits.

| Hits | Disposition |
|---|---|
| implementation-plan.md:233 (AC-21 row) | updated: (g) and (f) wording as above. The `stays green` hit is the (f) clause, since reworded. |
| implementation-plan.md:320–322, 344, 350–385, 560–562 | updated: preamble, §3, baseline bullet, stage contract. The `FailedCount` hit at :360 is the prose explaining why FailedCount alone is not trusted. |
| task.md:40, 54, 56, 59 | updated: rows 0, 7a, 7c, H1-2. |
| implementation-plan.md:83, 103, 253, 277–282, 535; task.md:13, 42, 51, 53, 55 | confirmed-consistent: AC-21 part references from the merge, or `Pester`/`baseline` mentions that stay correct. |

**Plan-file hashes at this point.** implementation-plan.md `f970c5a8c98c9493c1db45c2d2e45a02931b64827128fe48e74846996cb30e1b`; task.md `9c003ed094021376e198292fac4507c10a3221eaeef97310f826f241296ec40c`; run_pester.ps1 `68d3eaa2fe9327602cf1ecd277084b0edbe7b3876613611e72034aa31a6b27db`; new_failures.py `233c58a65bc80a73c3301b5ea344f30c18d9df408ff7427ff6bff1b6584c73c0`; stage_core.py `3af37cbc0169c91ac92b0c8ddc08702690df247aa6954ba2f54693bc46e7ac35`; check_ac17.py `25f8d2e051b30027612303d07ce02c8daeb7878966a46b01936b2eba0f3bd0c2`.

**Next step (human decision, 2026-10-20).** The human chose "Record r3, grant 1 round". Round 3 was then recorded from `C:/Temp/agentic-framework/receipts/dispatch/review-limits-plan-r3/final.renumbered.json`. That file is `final.json` with exactly one field changed, F-008 `violates` `AC-27` → `AC-21`, which was checked by a field-by-field diff; `final.json` itself is untouched. The record printed `OK: recorded round 3 verdict=changes_required … blocking=1 … usage=5,234,348`. `continue --rounds 1 --by MatBanik` then printed `OK: continue recorded by MatBanik at 2026-10-20T17:04:32-04:00: +1 round(s), +0 tokens; lifted budget`. The ledger reads `rounds 3/4`, `tokens 17,602,001/31,500,000`. The corrected plan goes to review round 4, the last one.

## Recheck (2026-10-20) — Round 4

**Workflow:** `/plan-critical-review`; **reviewer:** `gpt-6.1-sol` (dispatch command and shared registry); **requested_verbosity:** `standard`; **verdict:** `changes_required`; **intent_achieved:** `partial`.

**Intent anchor:** “Make review round caps and token budgets setup choices in the repo, adopted by each plan and execution as tighten-only defaults, with loosening only through a verified human-typed offer.” The WP-1–WP-5 product design addresses that goal, including the human's resolved D-1, but the replacement regression gates can still approve failed or incomplete runs.

### Scope and Procedural Gate

Reviewed the unstarted `implementation-plan.md`, `task.md`, `run_pester.ps1`, `new_failures.py`, `stage_core.py`, and unchanged `check_ac17.py`, against the cited ledger, run-parameters, instantiate and credits entrypoints. Implementation rows remain unchecked; the project implementation handoff does not exist. `task.md`'s `in_progress` frontmatter does not establish implementation. No execution was started.

**PR-6 was checked before substantive recheck: PASS.** The named census has SHA-256 `e0f5930116a2ae1cdfe0465df5f037d56bee90ceebd9882b097c20af0e35cc99`, 124 lines, 19 complete sweep/exit pairs, seven exit-1 empty sweeps, and 45 unique carrier `file:line` hits. Every hit falls within an explicit disposition in the correction log. Comparing every raw hit with the live carrier finds only implementation-plan.md:233 different, exactly the disclosed AC-21(f) edit. This is a complete, dispositioned census with a disclosed subsequent wording change, not a procedural refusal.

### Findings

All findings have **High confidence**. `P` below means `docs/execution/plans/2026-10-20-review-limits-parameters/`.

| # | Severity | Blocking | Kind | Finding | File:Line | Recommendation | Status |
|---|---|---|---|---|---|---|---|
| F-008 | High | yes | control-defeat | **The baseline Pester branch still false-passes a failed run.** The original discovery case is fixed, but failure enumeration omits a failed `AfterAll` block. An actual Pester 5.7.1 run with an empty baseline printed `Pester gate PASS: Result=Failed Passed=1 Failed=0 FailedContainers=0 ... Baseline=0 Unexcused=0` and exited 0. The same run without `-Baseline` exits 1. This uses the clean-baseline path selected by rows 7a/7c and §3, so no pre-existing failure is needed. AC-21(g)'s negative gate contract is violated. **mechanism: task-row-completion-predicate** (carried from round 3). | P/run_pester.ps1:34, :47; P/task.md:54, :56; P/implementation-plan.md:368 | Account for failed blocks and every non-passing outcome; refuse any failed outcome not fully explained by allowed failure records. Add the clean-baseline `AfterAll` negative case to the self-check. | open |
| F-010 | High | yes | control-defeat | **An interrupted pytest run is accepted as completed.** A real three-test probe passed its first test, raised `KeyboardInterrupt` in its second, and never ran its third. Pytest exited 2 and printed `1 passed in 0.21s`; the unchanged helper then exited 0 with `new-failures PASS: 0 new, 0 pre-existing`. Its summary regex accepts interruption summaries, and callers discard/overwrite the pytest status. Row 0's same summary-only completeness check also accepts this baseline. A receipt containing a failure count but no failure IDs is likewise accepted. This violates AC-21(g)'s completed-regression and negative-gate contract. **mechanism: swallowed-exit-code**. | P/new_failures.py:27, :35; P/task.md:40, :56, :59; P/implementation-plan.md:344, :367, :379 | Preserve the pytest exit code through location/receipt reads; only completed exit 0/1 runs may enter baseline comparison. Validate both receipts, reconcile failure/error counts with IDs, and exercise a real interruption/internal-error negative oracle. | open |
| F-011 | Medium | no | control-defeat | Failure IDs alias different tests/containers. A baseline with one `same.name` excuses two failing tests in different files; `container:Same.Tests.ps1` excuses two discovery failures in different directories. Both probes exit 0. This disproves the helper's general claim that a new failure cannot be excused. It is non-blocking for the disclosed current Pester baseline because that list is empty. Pytest IDs contain their paths, but comparing only an existing failed node ID also cannot distinguish a new failure cause in that same node. **mechanism: baseline-identity-collision**. | P/run_pester.ps1:37, :38; P/new_failures.py:38; P/implementation-plan.md:371 | Use normalized stage-relative file identities plus test/data-case identity; reject ambiguous duplicate identities. Keep WP-5-critical baseline failures visible and check their failure causes, or restore those tests to green before using them as regression evidence. | open |
| F-012 | Low | no | clerical | The live task linter refuses row 0: `references the receipts dir but not a path under it ("C:/Temp/agentic-framework/receipts'); ok")`. The inline Python directory literal trips its receipt-path check, despite the correction log's reported passing lint. | P/task.md:40 | Express the inline receipt directory through the environment/path representation the task linter accepts, then preserve the fresh lint result. | open |

### Prior Findings and Confirmed Corrections

| Prior item | Recheck |
|---|---|
| F-008 discovery-failure case | Fixed specifically: discovery plus an unaffected passing container exits 1, with and without an empty baseline. The replacement gate's incomplete outcome predicate remains blocking as shown above. |
| F-009 stale registration | Fixed faithfully. The old AC-21–AC-27 descriptions/negative tests map to AC-21(a)–(g). Parts (a)–(e) and the (f) description are unchanged. Only the disclosed staged wording in (f)'s negative check and baseline-based replacement of (g)'s green-suite clause differ. No product requirement was dropped in the merge. |
| Round-3 recording | `final.renumbered.json` equals `final.json` after changing exactly F-008 `violates` from `AC-27` to `AC-21`. Old AC-27 is now AC-21(g), the same regression-gate contract. This is a faithful citation remap. No AC-22–AC-27 reference remains in the live plan/task. |
| Round grant | Read-only ledger inspection confirms three recorded rounds and the one-round grant by MatBanik at `2026-10-20T17:04:32-04:00`; AC-1–AC-21 remain registered. Round 4 is the last authorized round. |
| `stage_core.py` | Resolves the working tree's `core/`, copies it afresh, then fills and verifies it. Injected instantiate exit 7 returns 7 without verification; verify exit 8 returns 8. A real fill/verify in a receipts-local stage passed. Only the two output-directory constants were redirected in memory to respect this review sandbox; production source was unchanged. |
| `check_ac17.py` | Hash unchanged. Its negative oracle executes against `d698342` and finds 27 problems; the unstarted working tree also fails with 27 problems, as expected before WP-4. The bounded inventory and manual in-place prose review remain the AC-17 contract. |

**Earlier substance holds.** WP-1 retains setup flags/config precedence and shipped-default identity tests; WP-2 retains repo → plan → tighten-only flags, explicit `off`, provenance, strict malformed-input refusal and legacy compatibility. WP-3 retains verified human-typed self-contained offers and the ledger-derived final audit cap (no unverified task-block fallback). WP-4 retains both carriers, source-attributed cap prose, setup questions, template versions and manifest changes. WP-5 retains optional-cap schema/runtime checks, present-cap enforcement, admission-time switch rechecks, zero-reservation uncapped launch, exposure and chain-room semantics, and the manual runner's unchanged default. File dependencies exist or are explicitly scheduled creations; the missing run-parameters policy is the disclosed disabled setup, not an undisclosed prerequisite. No new product decision is needed.

### Checklist Results

| Check | Result | Observed evidence |
|---|---|---|
| PR-1 / PR-2 / PR-3 | pass | Plan/task package order and outputs agree; implementation unchecked; canonical implementation handoff absent; task table contains all required columns and ownership. |
| PR-4 / PR-8 / DR-4 | fail | Actual interrupted-pytest and clean-baseline Pester hook-failure probes false-pass. The remaining direct commands in rows 7/7a preserve nonzero statuses; stage failure paths stop. Rows 0/7c/H1-2 and §3 comparisons need F-010's completion handling. |
| PR-5 / PR-7 | pass | Human-approved D-1/D-2 and local precedents remain explicit; exclusions preserve manual-runner and unrelated-mode scope boundaries. |
| PR-6 | pass | Full hash/disposition audit above; performed first. |
| PR-9 / DR-2 / DR-3 / DR-6 | pass within scope | Shared limits contract remains governing; live old AC-22–AC-27 references are absent, merge preserves requirements and linkage. |
| DR-1 / DR-5 / DR-7 | partial | Helper bytes and census match disclosed hashes; Pester baseline receipt hash and 324/0 counters match. Live lint does not match the reported green lint. Credits historical receipt confirms counts but cannot prove all failure causes. |
| DR-8 | pass | Plan remains unimplemented and no implementation-complete claim is made. |

### Durable Observations and Commands

Probe artifacts are under `C:/Temp/agentic-framework/receipts/rl-r4/`. These are review fixtures, not repository test/product changes. The probe drivers finish with exit 0 while recording each child's actual exit; their wrapper success is not a passing gate verdict.

```json
{"schema_version":"evidence.v1","check_id":"r4-pr6","procedure":"SHA-256 the raw census; count sweep boundaries/exits; enumerate unique carrier file:line hits; map every hit to the correction-log disposition ranges; compare every raw hit with its current carrier before reviewing the corrections.","observer":"gpt-6.1-sol","exit_code":null,"result":"pass","phase":"manual","scope":"PR-6","tested_state":"implementation-plan f970c5a8c98c9493c1db45c2d2e45a02931b64827128fe48e74846996cb30e1b; task 9c003ed094021376e198292fac4507c10a3221eaeef97310f826f241296ec40c","output":"hash e0f5930116a2ae1cdfe0465df5f037d56bee90ceebd9882b097c20af0e35cc99; 124 lines; 19 boundaries and 19 exits; 45 unique hits; undispositioned []; current differences only implementation-plan.md:233, disclosed (f) wording"}
```

```json
{"schema_version":"evidence.v1","check_id":"r4-pytest-completion","command":"rtk proxy python -B -X utf8 C:/Temp/agentic-framework/receipts/rl-r4/probe_pytest.py","exit_code":0,"result":"fail","phase":"targeted","scope":"AC-21(g) pytest gate","tested_state":"new_failures.py 233c58a65bc80a73c3301b5ea344f30c18d9df408ff7427ff6bff1b6584c73c0","output":"actual pytest exit 2; one passed, third test unrun; helper exit 0 and new-failures PASS. Both quiet/full summaries match; no-summary crash and pre-summary truncation refuse; new FAILED ID refuses; summary-without-failure-IDs and INTERNALERROR-with-summary accept. Empty baseline accepts; same failed node ID with different failure cause is excused."}
```

```json
{"schema_version":"evidence.v1","check_id":"r4-pester-outcomes","command":"rtk proxy python -B -X utf8 C:/Temp/agentic-framework/receipts/rl-r4/probe_pester.py","exit_code":0,"result":"fail","phase":"targeted","scope":"AC-21(f,g) Pester gate","tested_state":"Pester 5.7.1; run_pester.ps1 68d3eaa2fe9327602cf1ecd277084b0edbe7b3876613611e72034aa31a6b27db","output":"Discovery and BeforeAll refuse with no baseline and empty baseline; empty directory, zero-test file, missing baseline refuse; clean pass accepts. AfterAll with no baseline exits 1; the same failed run with an empty baseline exits 0: Result=Failed Passed=1 Failed=0 FailedContainers=0 Baseline=0 Unexcused=0. Two distinct failures sharing ExpandedPath or container leaf are excused by one baseline ID."}
```

Pester probe qualification: default sandbox Pester configuration causes the helper's very first all-passing self-check to fail (exit 1), before real-run output. To inspect its outcome accounting independently, the probe driver disables only Pester TestRegistry/TestDrive through `$PesterPreference`; it executes the unchanged helper and its entire self-check before each real fixture. The exact CLI `rtk proxy pwsh -NoProfile -File .../run_pester.ps1 ''` rejects an empty string path with exit 1. An exploratory `-Command` wrapper initially masked that parameter-binding exit; that wrapper result is discarded. No claim is made that the full production Pester suite passed in this sandbox.

```json
{"schema_version":"evidence.v1","check_id":"r4-stage","command":"rtk proxy python -B -X utf8 C:/Temp/agentic-framework/receipts/rl-r4/probe_stage.py --real","exit_code":0,"result":"pass","phase":"targeted","scope":"working-tree stage and subprocess failure propagation","tested_state":"stage_core.py 3af37cbc0169c91ac92b0c8ddc08702690df247aa6954ba2f54693bc46e7ac35","output":"copy source P:/agentic-framework/core; instantiate failure returns 7 with no verify; verify failure returns 8; real copy/fill/verify with receipts-local output overrides returns 0, verify OK (0 placeholder tokens remain)."}
```

```json
{"schema_version":"evidence.v1","check_id":"r4-ac-merge","command":"rtk proxy python -B -X utf8 C:/Temp/agentic-framework/receipts/rl-r4/verify_merge.py","exit_code":0,"result":"pass","phase":"static","scope":"old AC-21–AC-27 against merged AC-21(a–g)","tested_state":"old raw census-rl-r3 receipt and current plan","output":"all seven parts present; (a–e) descriptions and negatives exact; (f) description exact and negative staged wording disclosed; (g) baseline rewrite disclosed. Six current target hashes match the correction-log hashes."}
```

```json
{"schema_version":"evidence.v1","check_id":"r4-task-lint","command":"rtk proxy python -B -X utf8 core/tools/lint_task_contract.py --task docs/execution/plans/2026-10-20-review-limits-parameters/task.md","exit_code":1,"result":"fail","phase":"static","scope":"live task contract","tested_state":"task 9c003ed094021376e198292fac4507c10a3221eaeef97310f826f241296ec40c","output":"REFUSE: task.md:40 row 0 references the receipts dir but not a path under it (C:/Temp/agentic-framework/receipts followed by inline Python punctuation)."}
```

**Baseline limits:** the historical `rl-stage/pester-probe2.txt` bytes hash to the disclosed `3eb052c20e904bbe03c3303938eadca1b43375659dfbf8a57c9b86e377bc3400`; it reports 21 files, 324 passed, zero failed/containers/skipped and exit 0; `probe-failures.txt` is empty. The historical credits output `.../tasks/bqdjup6fq.output` reports 17 failed, 459 passed, 50 skipped, 1456 deselected, 50 warnings, but contains only three FAILED IDs and no tracebacks. `psutil` is currently absent; the receipt does **not** independently establish that all 17 failures have that cause. A complete fresh `-rfE` row-0 receipt is necessary. ID-only forgiveness also cannot prove a previously failing WP-5 test did not regress; changed failure causes must be examined and required new/changed cases still pass directly. No historical or synthetic receipt is substituted for execution row 0.

### Verdict, Follow-up and Limits

`changes_required` — two High blocking findings, F-008 and F-010, both citing registered **AC-21**, plus two non-blocking observations. The original discovery defect and stale AC registration are corrected; the new baseline gates still do not prove completed, non-regressed validation.

This is **round 4 of 4**. Stop at the ledger boundary. Do not dispatch another review, reset the loop, start `/plan-corrections`, or begin implementation autonomously. The human's earlier execution authorization and explicit extra review round are acknowledged. Any next action must preserve this verdict and the exhausted review history; the user decides how to proceed. Remaining product work is unstarted, and implementation validation remains prospective.

Pre-Edit Guard: the sole repository edit is an append to `.agent/context/handoffs/2026-10-20-review-limits-parameters-plan-critical-review.md`, derived from the supplied target folder. Earlier bytes and frontmatter are preserved. No plan, product, tool, or repository test was edited; no commit was created. The final response is the requested v2 JSON, so the timestamp is embedded here instead of appended outside that JSON.

🕐 Completed: 2026-10-20 17:12 (EDT)

## Corrections Applied — Round 4 F-008, F-010, F-011 and F-012 (planner, 2026-10-20, after round 4)

**Ledger state, disclosed first.** Round 4 is recorded (`changes_required`, 2 blocking). The ledger refused the verdict as returned, because the mechanism names `swallowed-exit-code` (F-010) and `baseline-identity-collision` (F-011) are not in the closed vocabulary `core/.agent/context/review-vocabulary.yaml`. It was recorded from `C:/Temp/agentic-framework/receipts/dispatch/review-limits-plan-r4/final.remapped.json`, in which both mechanisms read `task-row-completion-predicate` (the catalogued mechanism F-008 already carries). That is the only field changed; `final.json` is untouched. The ledger then stopped the loop: rounds 4/4, and a mechanism-class stop, since four blocking findings share `task-row-completion-predicate` ("redesign the mechanism rather than patching the instance").

**Planner error, disclosed.** The round-3 correction log reported a passing task lint. That lint ran with `RECEIPTS_DIR` unset; with it set, row 0 is refused, exactly as F-012 says. Every lint below ran with `RECEIPTS_DIR` set.

**Framework defect (for the known-issues register).** The closed mechanism vocabulary refuses a reviewer's new mechanism name at `record`. The planner then has to remap reviewer output to a catalogued name before the round counts.

**Human decision.** Asked how to continue, the human chose "Install psutil, plain gates (Recommended)": install `psutil`, confirm the staged credits baseline turns green, make every gate require exit 0 with nothing failed, drop `new_failures.py` and the `-Baseline` mode, make the Pester gate refuse any `Result` other than `Passed`, fix F-012, and grant one round with the mechanism relieved. The redesign answers the mechanism stop: no gate excuses a failure, so there is no comparison to defeat.

| Finding | Change |
|---|---|
| Environment | `python -m pip install psutil` (7.2.2) into `C:/Python314`. The plan's Verification preamble now requires `psutil` and names why (`credits_msg.py:2042`). |
| F-008 (AfterAll false-pass) | `run_pester.ps1` has no `-Baseline` or `-FailuresOut`. It passes only when `Result` is `Passed`, `PassedCount` ≥ 1, and `FailedCount`, `FailedBlocksCount` and `FailedContainersCount` are all 0. Its self-check, run before the real run, must pass a passing file and refuse an assertion failure, a discovery failure beside a passing file, a `BeforeAll` failure beside a passing file, an `AfterAll` failure after a passing test, and a file with no test. A failed self-check exits 1. Probed: a passing file gives `PASS` exit 0; that file plus an `AfterAll` failure gives `FAIL: Result=Failed Passed=2 Failed=0 FailedBlocks=1` exit 1. |
| F-010 (interrupted pytest accepted) | `new_failures.py` is deleted. Every pytest gate is pytest's own exit status, captured in `$code` straight after the redirected run and re-raised. Only 0 passes, so an interrupted run or a collection error (2), an internal error (3) and an empty selection (5) cannot pass. Rows 0, 7c, H1-2 and §3 updated; row 7c's `Pop-Location` comes after the capture. |
| F-011 (id aliasing) | Moot: no failure id is compared any more. |
| F-012 (lint) | Row 0's inline receipts-dir literal was in the deleted completeness check; it is gone. |
| Row 0 | Records the identity (HEAD, porcelain, Python and `psutil` versions, `RECEIPTS_DIR`, `AGENT_MODEL_REGISTRY_HOME`) into `rl-identity-baseline.txt`, and refuses when `psutil` is missing or `AGENT_MODEL_REGISTRY_HOME` is unset. Then the full pytest, `stage_core.py`, the staged credits pytest and `run_pester.ps1`, each of which must exit 0; the first failure ends the row. A red baseline stops execution for the human. |
| AC-21 (g) | Now: "Run in the instantiated stage, the credits pytest and every Pester suite pass outright, as they do at row 0, the new and changed tests pass, and the existing fixtures are unchanged." Negative check: "In the stage, the credits pytest exits 0, and `run_pester.ps1` passes on every Pester suite. An interrupted pytest run exits 2 and cannot pass. `run_pester.ps1` refuses an assertion failure, a discovery failure, a `BeforeAll` failure, an `AfterAll` failure and a file with no test (its self-check)." Parts (a)–(f) are unchanged. Sources gain "review round 4, F-008, F-010". |
| Plan §3, stage contract | §3 drops both comparison commands and explains the two plain gates. Blocking: "every stage blocks, and no failure is excused." |

**Green baseline, observed on the unchanged product tree** (only the plan folder and this handoff differ from HEAD `e667fb6`), with `AGENT_MODEL_REGISTRY_HOME=P:/.agent`. Receipts are under `C:/Temp/agentic-framework/receipts/rl-psutil/`:

| Run | Result | Exit | sha256 |
|---|---|---|---|
| `stage_core.py` | verify OK | 0 | `778e6d2b8bfd049faf1343f56cd775e73a2d249a58170ce1739b189ae8de4126` (`stage.txt`) |
| staged `pytest tools/tests -k credits -q -rfE` | 476 passed, 50 skipped, 1456 deselected | 0 | `02d288035cf9a311eae53ee4289ec7d7a8e598a3e90d9aca490879d8e59c72fa` (`credits-stage.txt`) |
| full `pytest core/tools/tests scripts/tests -q -rfE` | 2072 passed, 36 subtests passed | 0 | `67727cf3821b7359e6b240236caf6ce3ed96494701ed0f21c246d19fb6f4a775` (`full-pytest.txt`) |
| `run_pester.ps1` on the staged `tools/tests` | `PASS: Result=Passed Passed=324 Failed=0 FailedBlocks=0 FailedContainers=0 Skipped=0` | 0 | `218046fc3b5375c57b6d755f2cc69a66be993122ae54b95588c1255166ae2607` (`pester-stage.txt`) |

These are planner observations, not row 0: row 0 still runs fresh at execution.

**Lint.** With `RECEIPTS_DIR=C:/Temp/agentic-framework/receipts`: `OK: 39 row(s); … 37 row(s) fully checked …; 2 row(s) exempt (view_file): H1-5, H2-1`, exit 0 (receipt `rl-psutil/lint-set.txt`, sha256 `2d33195e096afad1968b04aad0509b2316f6a0f051682c3e31aa36ee543ac1f4`). The same result with it unset.

**Census (Step 5c).** Receipt: `C:/Temp/agentic-framework/receipts/census-rl-r4/census-review-limits-r4.txt` (sha256 `8ba0076dcc27a7b457616a663680b9a928381da433a35dcd7e2a5cc71a042a34`). It has 17 sweeps (`rg -F -n` over both plan files): `new_failures`, `-Baseline`, `FailuresOut`, `baseline lacks`, `pre-existing`, `rl-pester-baseline-failures`, `rl-full-pytest-compare`, `rl-credits-compare`, `may fail`, `summary line`, `psutil`, `run_pester`, `baseline`, `AfterAll`, `exit 2`, `no failure is excused`, `FailedCount`. The first 10 end `# rg exit 1`: the retired comparison design is gone. There are 19 unique `file:line` hits.

| Hits | Disposition |
|---|---|
| implementation-plan.md:233 (AC-21 row) | updated: (g) text, (g) negative check, sources. |
| implementation-plan.md:322–325, 357–376, 557 | updated: preamble, §3 gates and prose, baseline bullet, Blocking. |
| task.md:40, 54, 56 | updated: rows 0, 7a, 7c. (H1-2 at task.md:59 also changed; none of the swept terms remains in it.) |
| implementation-plan.md:204, 214 | confirmed-consistent: `exit 2` is `instantiate.py`'s usage error, unrelated to the gates. |

**Plan-file hashes at this point.** implementation-plan.md `f970362bfae2655c415dae6c6f02aa6cce4f3f7e67e6872122633449ff3b803a`; task.md `d35047411b01b449cba0bc05149125320423934ddd96afe0ab56315192d825d3`; run_pester.ps1 `51d00fd5090392a7c04d0e87f049cdb9e95acf1ac46b594c4e6488f8f7758d96`; stage_core.py `3af37cbc0169c91ac92b0c8ddc08702690df247aa6954ba2f54693bc46e7ac35` (unchanged); check_ac17.py `25f8d2e051b30027612303d07ce02c8daeb7878966a46b01936b2eba0f3bd0c2` (unchanged).

**Next step.** The human granted round 5 with the mechanism relieved; the ledger `continue` records it. Round 5 is the last authorized round.


## Recheck (2026-10-20) — Round 5

**Agent:** gpt-6.1-sol (dispatch argv and live model registry); **requested_verbosity:** standard.
**Loop:** review-limits-parameters-plan-2026-10-20; last authorized round, 5 of 5.

### Intent Anchor

"Make review round caps and token budgets setup choices in the repo, adopted by each plan and execution as tighten-only defaults, with loosening only through a verified human-typed offer."

The substantive WP-1–WP-5 plan still describes that objective. Intent achieved: **partial**, because the required launcher-suite validation can pass without running that suite.

### Findings

P/ below means docs/execution/plans/2026-10-20-review-limits-parameters/.

| ID | Severity / Confidence | Blocking | Kind | Finding | File:Line | Recommendation | Status |
|---|---|---|---|---|---|---|---|
| F-013 | High / High | yes | control-defeat | **An explicitly required Pester suite can be absent while its gate passes.** Subject: committable-tooling. Invoke-Run forwards paths without checking that each requested suite exists or was discovered; Test-Gate checks aggregate outcomes only. The unchanged helper, given the real staged Register-CreditsRun.Tests.ps1 and a nonexistent Start-CreditsRun.Tests.ps1, ran the registration suite's 40 tests and exited 0: Result=Passed, Passed=40, all failure counters 0. Pester emitted a missing-path diagnostic, but the helper accepted its remaining result. Row 7a names both suites to prove the optional-cap schema and uncapped launcher argv; its required launcher acceptance assertions can therefore be materially absent while the row's command succeeds. **Violated contract: AC-21 (f), (g). mechanism: task-row-completion-predicate.** | P/run_pester.ps1:27, :32, :77; P/task.md:54; P/implementation-plan.md:233 | Refuse a missing or undiscovered explicitly requested suite before accepting aggregate success. Add the paired negative case: an existing passing suite beside a missing required suite must exit nonzero. Preserve the plain outcome checks and immediate pytest status capture. | open |

This is a missing-input/scope failure: no failed Pester result is produced for the omitted suite. It is materially different from the corrected F-008 discovery/AfterAll outcome accounting. The finding demonstrates missing required AC-21(f) validation, rather than requesting more predicate-shape mutations.

### Scope and PR-6 Gate — Evaluated First

Reviewed both plan files, run_pester.ps1, stage_core.py, unchanged check_ac17.py, related live producers/callers, the correction log and its named receipts. All 39 task rows remain unchecked; the project implementation handoff is absent. No implementation-complete claim is made.

PR-6 **passes**. The raw census SHA-256 is 8ba0076dcc27a7b457616a663680b9a928381da433a35dcd7e2a5cc71a042a34. All 17 sweeps reproduce their complete hit lines and rg exits against the current plan files; all 19 unique file:line hits fall within the correction log's updated/confirmed-consistent dispositions. All five live plan-folder file hashes match the log. The deleted new_failures.py is absent.

The round-4 remap is faithful: a field-by-field comparison finds exactly F-010's mechanism changed from swallowed-exit-code and F-011's from baseline-identity-collision to task-row-completion-predicate. Blocking, severity, finding text and every other field are unchanged. Both describe a false acceptance by a task-completion check, fitting the catalogued control. F-011 remains non-blocking and contributes no blocking recurrence. Ledger state independently confirms rounds 4/5 before this verdict, the human's round-5 grant and the named mechanism relief; NEXT ROUND is permitted.

### Prior Findings and Confirmed Corrections

| Prior item | Round-5 result |
|---|---|
| F-001–F-007 / WP-1–WP-4 | Remain corrected in the plan. Repo defaults and instantiate precedence; strict parser, carrier equality, tighten-only flags and explicit off; self-contained human-typed loosening; ledger-based audit with missing/malformed/wrong-mode refusals; bounded cap inventory, source-reading and template selftests remain specified and mapped to task rows. |
| F-008 | **Fixed for the reported failures.** Assertion, discovery, BeforeAll and AfterAll failures each exit 1. AfterAll now reports FailedBlocks=1 and refuses despite FailedCount=0. Skipped-only, zero-test, empty-directory, empty-string and missing-only inputs also refuse. Every successful self-check precedes the real run; a forced failing self-check exits 1 without reaching it. F-013 is the separate paired-input case. |
| F-010 | **Fixed.** All 12 pytest invocations across plan/task capture LASTEXITCODE immediately into code. Actual pytest interruption, internal-error and empty-selection runs remain exits 2, 3 and 5 through rows 0, 7c, H1-2 and both relevant section-3 command forms (15 probes). No receipt read or Pop-Location precedes capture. |
| F-011 | **Removed with the comparison design.** No failure-ID comparison or baseline-forgiveness execution path remains. |
| F-012 | **Fixed.** Fresh task lint with RECEIPTS_DIR set exits 0: 39 rows, 37 fully checked, two source-read exemptions, acyclic dependencies. |
| Row 0 prerequisites and stop | Actual identity command exits 0 with psutil 7.2.2 and the registry set, 1 with the registry unset, and 1 when Python's site packages are disabled so psutil cannot import. A failing first pytest stops the row with its original status before staging or Pester. |
| AC-21(a)–(f) | Unchanged since round 4. Compared to the earlier raw census, descriptions and negatives are exact except the already-disclosed (f) negative wording replacement, "passes in the stage, where it also passes at baseline." No additional change appeared in this correction. |
| AC-21(g) | Still requires skill disclosure, passing staged suites, passing new/changed tests, unchanged fixtures and the unchanged manual $2 default. Its negative check explicitly refuses interrupted pytest and the five Pester failure/empty cases. The regression contract is preserved; F-013 defeats required-suite coverage. |

WP-5's producers and contrasting oracles remain substantive: optional cap registration and partial-cap floor behavior; admission-time switch re-read with failed/start_refused versus stopped/resume_refused; zero exposure with cost_known=0; None chain room and whole-block equality; explicit MaxBudgetUsd 0 reaching argv omission through Invoke-ClaudeCredits.ps1:272. Present caps, segment timeout, resume authority and the manual default retain their stated boundaries. The new loader remains WP-2's dependency; WP-5 follows WP-4 in task order. New implementation test/config paths are scheduled creations; existing invoked helpers and tools exist.

Retired-term sweep: no new_failures.py, -Baseline, -FailuresOut, rl-pester-baseline-failures.txt or "baseline lacks" remains in the live plan folder. One harmless wording residue remains at run_pester.ps1:10: "A pre-existing failure is not excused." This negates the retired behavior and introduces no comparison; optional cleanup only.

### Baseline Evidence and Limits

The claimed unchanged-tree baseline is supported. HEAD is e667fb689980ce47d32c0e6fd154779f3c23c9cc; product sources remain unchanged, with only the plan folder and rolling review untracked. All five disclosed baseline/lint receipt hashes match exactly:

| Receipt | SHA-256 | Observed decisive output |
|---|---|---|
| stage.txt | 778e6d2b8bfd049faf1343f56cd775e73a2d249a58170ce1739b189ae8de4126 | verify OK, zero placeholder tokens |
| credits-stage.txt | 02d288035cf9a311eae53ee4289ec7d7a8e598a3e90d9aca490879d8e59c72fa | 476 passed, 50 skipped, 1456 deselected |
| full-pytest.txt | 67727cf3821b7359e6b240236caf6ce3ed96494701ed0f21c246d19fb6f4a775 | 2072 passed, 36 subtests passed |
| pester-stage.txt | 218046fc3b5375c57b6d755f2cc69a66be993122ae54b95588c1255166ae2607 | self-check precedes 324 passing tests; Passed result, zero failed/skipped |
| lint-set.txt | 2d33195e096afad1968b04aad0509b2316f6a0f051682c3e31aa36ee543ac1f4 | 39 rows; 37 fully checked |

These are verified planner full-run observations, **not independently rerun full suites**. An independent receipt-local stage made from current core verifies successfully; its 268 non-cache files match the planner stage after substituting only the two configured stage/receipt root paths. Stage failure injection preserves instantiate exit 7 and verify exit 8, stopping at the first error. The original hard-coded stage target was not deleted or rewritten by this reviewer.

Sandbox qualification: the default Pester configuration fails the helper's initial positive self-check, exit 1, before the real run. Outcome probes therefore disable Pester TestRegistry and TestDrive; the decisive real-suite F-013 probe disables only TestRegistry, leaving TestDrive enabled. The helper and its full self-check are unchanged in both cases. This is targeted gate evidence, not a claim of a fresh default-configuration full Pester pass.

### Checklist Results and Durable Observations

| Check | Result | Observation |
|---|---|---|
| PR-1 / PR-2 / PR-3 | pass | WP-1–WP-5 align; 39 unchecked rows; implementation handoff absent; live lint passes with receipts environment set. |
| PR-4 / PR-8 / DR-4 | fail | F-013 proves a required explicitly named suite may be missing while the gate exits 0. |
| PR-5 / PR-7 | pass | Human D-1/D-2 choices and local precedents remain explicit; no disguised deferral or lost scheduled credits work. |
| PR-6 | pass | Complete reproduced census, digest, per-hit dispositions, target hashes and faithful remap checked before substantive review. |
| PR-9 / DR-2 / DR-3 / DR-6 | pass with note | Shared contract still governs; no conflicting live cap or comparison path. Harmless retired phrase noted above. |
| DR-1 / DR-5 / DR-7 | pass with limits | Correction bytes and fresh lint agree with claims; baseline receipt hashes/counts and staged input identity verified. Full suites reused as observations, not rerun. |
| DR-8 | pass | Execution is unstarted; implementation tests remain prospective. |

~~~json
{"schema_version":"evidence.v1","check_id":"r5-census-remap-baseline","command":null,"procedure":"Hash the named census and five current plan-folder files; reproduce each census term with rtk proxy rg -F -n and compare complete hit lines and exits; check all 19 unique hits against disposition ranges; recursively compare original/remapped r4 JSON after changing only the two named mechanism fields; hash and inspect all five baseline receipts; compare the two staged file inventories after substituting their configured root paths.","observer":"gpt-6.1-sol","exit_code":null,"result":"pass","phase":"manual","scope":"PR-6, remap fidelity and baseline premise","tested_state":"HEAD e667fb689980ce47d32c0e6fd154779f3c23c9cc; plan f970362bfae2655c415dae6c6f02aa6cce4f3f7e67e6872122633449ff3b803a; task d35047411b01b449cba0bc05149125320423934ddd96afe0ab56315192d825d3","output":"17 complete sweeps, 19 unique hits, all dispositioned; all declared hashes match; only two mechanism fields remapped; staged inventories each 268 files, no non-path differences; full pytest 2072 passed and 36 subtests; credits 476 passed; Pester 324 passed."}
~~~

~~~json
{"schema_version":"evidence.v1","check_id":"r5-pester-outcomes","command":"rtk proxy python -B -X utf8 C:/Temp/agentic-framework/receipts/rl-r5/probe_pester.py","exit_code":0,"result":"pass","phase":"targeted","scope":"Pester outcome refusals and self-check ordering","tested_state":"run_pester.ps1 51d00fd5090392a7c04d0e87f049cdb9e95acf1ac46b594c4e6488f8f7758d96; Pester 5.7.1","output":"Passing file exits 0. Assertion, discovery, BeforeAll, AfterAll, skipped-only, zero-test, empty directory, empty string and missing-only path exit 1. Self-check precedes real run; forced self-check failure exits 1 without real-run output. TestRegistry/TestDrive disabled for outcome isolation; default positive self-check independently refuses in sandbox."}
~~~

~~~json
{"schema_version":"evidence.v1","check_id":"r5-pester-required-scope","command":"rtk proxy python -B -X utf8 C:/Temp/agentic-framework/receipts/rl-r5/probe_pester_scope.py","exit_code":0,"result":"fail","phase":"targeted","scope":"AC-21(f,g), row 7a required launcher-suite coverage","tested_state":"unchanged helper 51d00fd5090392a7c04d0e87f049cdb9e95acf1ac46b594c4e6488f8f7758d96; independently instantiated current Register-CreditsRun.Tests.ps1; missing requested Start-CreditsRun.Tests.ps1","output":"Driver completes (exit 0); the tested gate incorrectly exits 0. paths_exist=[true,false]; self-check passes; Discovery found 40 tests; Pester gate PASS: Result=Passed Passed=40 Failed=0 FailedBlocks=0 FailedContainers=0 Skipped=0. stderr: Get-ChildItem: Cannot find path .../missing-required/ because it does not exist. Passing fixture plus missing fixture also exits 0. Only TestRegistry disabled for the real-suite probe."}
~~~

~~~json
{"schema_version":"evidence.v1","check_id":"r5-pytest-status","command":"rtk proxy python -B -X utf8 C:/Temp/agentic-framework/receipts/rl-r5/probe_pytest.py","exit_code":0,"result":"pass","phase":"targeted","scope":"all pytest capture sites; row 0 prerequisites; rows 0/7c/H1-2 and section 3 propagation","tested_state":"current plan/task hashes above; Python 3.14.7, psutil 7.2.2","output":"All 12 invocations capture immediately. Identity prerequisite: normal=0, missing registry=1, missing psutil via -S=1. Across five command chains, real interruption=2, internal error=3 and no selected test=5 (15/15). Row 0 stops before staging on the first failing pytest. Stage invocation replaced by a successful receipt-local stub in command-chain probes; pytest itself is real."}
~~~

~~~json
{"schema_version":"evidence.v1","check_id":"r5-stage","command":"rtk proxy python -B -X utf8 C:/Temp/agentic-framework/receipts/rl-r5/probe_stage.py --real","exit_code":0,"result":"pass","phase":"targeted","scope":"stage source, instantiate/verify failures and actual fill/verify","tested_state":"stage_core.py 3af37cbc0169c91ac92b0c8ddc08702690df247aa6954ba2f54693bc46e7ac35","output":"Copies current working core. Injected instantiate failure returns 7 without verify; injected verify failure returns 8; success returns 0. Actual receipt-local copy/fill/verify returns 0; verify OK, zero placeholder tokens. Only STAGE/RECEIPTS output constants overridden into reviewer receipts."}
~~~

~~~json
{"schema_version":"evidence.v1","check_id":"r5-task-lint","command":"rtk proxy python -B -X utf8 core/tools/lint_task_contract.py --task docs/execution/plans/2026-10-20-review-limits-parameters/task.md","exit_code":0,"result":"pass","phase":"static","scope":"live task contract with RECEIPTS_DIR set","tested_state":"task d35047411b01b449cba0bc05149125320423934ddd96afe0ab56315192d825d3","output":"RECEIPTS_DIR set to the configured external receipts root. OK: 39 rows; 10-column table; 37 fully checked; dependencies resolve and are acyclic; two view_file exemptions H1-5 and H2-1."}
~~~

The unchanged AC-17 oracle was also run: exit 1, self-check reports 27 problems at d698342 and 27 in the unstarted working tree. This expected red result confirms fixed caps have not yet been implemented; it is not a failed correction or a claim of completed WP-4.

### Verdict, Follow-up and Limits

**changes_required** — F-013 is one High blocking control-defeat finding citing registered AC-21. The earlier product intent and round-4 fixes otherwise hold, and the baseline premise is now supported. The remaining gate still permits materially absent launcher acceptance work.

This is the human-authorized **last round, 5 of 5**. Preserve the complete ledger/history and this result. Do not reset the loop, dispatch another review, start corrections or begin implementation autonomously; the human decides the next step at the exhausted boundary. The earlier execution authorization is acknowledged but does not convert this blocked review into approval.

Pre-Edit Guard: the derived write target is exactly .agent/context/handoffs/2026-10-20-review-limits-parameters-plan-critical-review.md. This section is appended; earlier sections and frontmatter are preserved byte-for-byte. Reviewer fixtures/receipts were written only under the allowed external receipts root. No plan, product, tool or repository test was edited, and no git commit was created. The final response uses the requested v2 JSON; the timestamp is embedded here to preserve that output contract.

🕐 Completed: 2026-10-20 19:40 (EDT)

## Corrections Applied — Round 5 F-013 (planner, 2026-10-20, after round 5)

**Ledger state.** Round 5 is recorded as returned (`changes_required`, 1 blocking, usage 5,568,458; no remap needed). The ledger then stopped the loop: rounds 5/5, and tokens 29,034,117 spent + 5,568,458 reserved > 31,500,000. Whether a sixth round runs is the human's decision.

**F-013 reproduced first.** The round-4 `run_pester.ps1`, given a passing file and a missing file, printed `Pester gate PASS: Result=Passed Passed=1 …` and exited 0.

| Change | Detail |
|---|---|
| `run_pester.ps1` coverage check | New `Get-UncoveredPath`: a requested path counts only if it exists and a discovered test file is that path or lies under it. The gate passes only when `Test-Gate` passes and no requested path is uncovered; each uncovered path is printed, and the summary line gains `Uncovered=<n>`. The self-check runs the same combined check. |
| Self-check cases | Added: a missing file beside a passing file → refuse; a directory with no test file beside a passing file → refuse; a passing directory requested in other letter case → pass. |
| Planner error, caught before this log | The first version compared directory prefixes with case. Pester reports the on-disk case (`C:\temp\…`) for a requested `C:/Temp/…`, so the full staged directory failed `Uncovered=1`. The prefix test is now `OrdinalIgnoreCase`, and the letter-case self-check case (verified: Pester reports on-disk case for an upper-cased request) would refuse the case-sensitive version. |
| Wording | The `.DESCRIPTION` residue "A pre-existing failure is not excused" now reads "No failure is excused". |
| Plan §3 Pester bullet, AC-21 (g) negative check | Name the requested-path rule and F-013's case: "a requested path, such as a missing `Start-CreditsRun.Tests.ps1` beside a passing `Register-CreditsRun.Tests.ps1`, that yields no test file". Sources gain "review round 5, F-013". (a)–(f) unchanged; task.md unchanged. |

**Observed after the fix** (`AGENT_MODEL_REGISTRY_HOME=P:/.agent`, receipts under `C:/Temp/agentic-framework/receipts/rl-psutil/`):

| Run | Result | Exit | sha256 |
|---|---|---|---|
| staged `Register-CreditsRun.Tests.ps1` + missing `Missing.Tests.ps1` | self-check passed; `requested path has no discovered test file: …/Missing.Tests.ps1`; `FAIL: Result=Passed Passed=40 … Uncovered=1` | 1 | `b421fc6a4c962d5360485c8fb3f734953f806d5bedfa3cec1e94a335bf0271ed` (`f013-missing.txt`) |
| staged `tools/tests` | self-check passed; `PASS: Result=Passed Passed=324 Failed=0 FailedBlocks=0 FailedContainers=0 Skipped=0 Uncovered=0` | 0 | `38eb8808314b8be86cae61c50a9432aba6f358f868d47823603c6b8be07ce01e` (`pester-stage-r5.txt`) |
| staged row-7a pair (`Start-CreditsRun`, `Register-CreditsRun`) | `PASS: … Passed=58 … Uncovered=0` (before the case fix; both are files, compared with `-eq`) | 0 | console only |
| task lint, `RECEIPTS_DIR` set | `OK: 39 row(s)` | 0 | console only |

**Plan-file hashes at this point.** implementation-plan.md `8344b78fcbdd6921caa051eecbedb3c1b7527c6cfe28d58881c3ec0b3e0c4fc6`; task.md `d35047411b01b449cba0bc05149125320423934ddd96afe0ab56315192d825d3` (unchanged); run_pester.ps1 `69940ba77e1943ce4df4dea07f5e96b8591c3e24f761c80adc943f6e23146535`; stage_core.py and check_ac17.py unchanged.

**Next step (human decision).** Grant a sixth review round (it needs both `--rounds 1` and `--tokens`, at least 3.1M more), accept the plan without re-review, or stop.

## Recheck (2026-10-20) — Round 6

**Workflow:** `/plan-critical-review` · **Agent:** `gpt-6.1-sol` · **Requested verbosity:** standard

**Intent anchor:** "Make review round caps and token budgets setup choices in the repo, adopted by each plan and execution as tighten-only defaults, with loosening only through a verified human-typed offer."

### Findings

| ID | Severity / Confidence | Blocking | Subject / Kind | Finding | File:Line | Recommendation | Status |
|---|---|---|---|---|---|---|---|
| F-014 | Medium / High | yes | review-scaffolding / behavior | **The F-013 resubmission lacks its correction census and per-hit dispositions.** The complete latest correction section names two Pester run receipts and file hashes, but no raw old/new-value blast-radius census receipt and no `file:line` dispositions marked `updated` or `confirmed-consistent`. The two plan carriers supply neither missing artifact. The named receipt directory contains seven run/lint/stage receipts, with no census. PR-6 explicitly requires both artifacts before corrected content may be reviewed. This blocks readiness evidence for the AC-21(g) Pester coverage correction; it does not demonstrate that the corrected script fails. **Violated contract: AC-21, reviewed under PR-6 and `plan-corrections.md` Step 5c.** | `.agent/context/handoffs/2026-10-20-review-limits-parameters-plan-critical-review.md:813`; `core/.agent/workflows/plan-critical-review.md:255`; `core/.agent/workflows/plan-corrections.md:191` | Supply and name an untruncated census over both plan files for the changed coverage predicate and its old/new semantic variants; give every hit an `updated` or `confirmed-consistent` disposition in the correction log. Preserve existing review history. | open |

F-014 represents the workflow's **procedural exception** in the required v2 finding object. Its Medium severity is an encoding of the missing review evidence, independent of its explicit blocking flag; no High delivery defect is asserted. `finding_kind: behavior`, `mechanism: null`: the PR-6 gate is refusing as designed, so this finding does not add a control-defeat recurrence. The absence of required artifacts is substantive to that gate, rather than a mislabeled receipt or a clerical disposition typo.

### Scope and PR-6 — Evaluated Before Substantive Review

Inspected the full latest correction section, both plan carriers for census references, the two named Pester receipts in full, all five plan-folder file identities, the governing workflow/template and correction-census rule, dispatch registry identity and current ledger state. The review retains the user-specified unstarted-plan scope. No implementation or test-completion claim is inferred from existing receipts.

**PR-6 fails.** The latest correction log has no census/disposition reference. `implementation-plan.md` also has none; the three `Updated` matches in task.md describe future deliverables at lines 45, 55 and 75, not correction dispositions. Historical census evidence belongs to earlier corrections and is not named as evidence for the F-013 change. The two newly cited receipts are real test-run output, not raw census sweeps.

Per PR-6 and the workflow's Verdict Rule, corrected content is **not substantively reviewed this round**. The requested missing/empty/discovery-failing paths, trailing slash, backslash, letter case, working-directory-relative path, sibling-prefix and duplicate-path probes are **not run**. The self-check's code and ordering, rows 0/7a/7c, section-3 command, AC-21(g) correspondence, prior plain-pytest/Result=Passed/prerequisite fixes and WP-1–WP-5 substance receive **no fresh substantive verdict**. F-013 remains unverified this round; no new script defect or closure is claimed.

### Receipt and Plan-File Identity Verification

All hashes below match the latest correction log or, for the unchanged helpers, the preceding verified identity. Both Pester receipts were read without truncation.

| Artifact | SHA-256 | Observed result |
|---|---|---|
| `f013-missing.txt` | `b421fc6a4c962d5360485c8fb3f734953f806d5bedfa3cec1e94a335bf0271ed` | Self-check text precedes 40 passing tests; missing requested file printed; `FAIL: Result=Passed ... Uncovered=1`. The process exit 1 is the planner's recorded observation; this receipt does not independently encode the process status. |
| `pester-stage-r5.txt` | `38eb8808314b8be86cae61c50a9432aba6f358f868d47823603c6b8be07ce01e` | Self-check text precedes discovery in 21 files and 324 passing tests; `PASS: Result=Passed Passed=324 Failed=0 FailedBlocks=0 FailedContainers=0 Skipped=0 Uncovered=0`. No independent suite rerun. |
| `implementation-plan.md` | `8344b78fcbdd6921caa051eecbedb3c1b7527c6cfe28d58881c3ec0b3e0c4fc6` | Matches declared corrected plan. |
| `task.md` | `d35047411b01b449cba0bc05149125320423934ddd96afe0ab56315192d825d3` | Matches declared unchanged task. |
| `run_pester.ps1` | `69940ba77e1943ce4df4dea07f5e96b8591c3e24f761c80adc943f6e23146535` | Matches declared corrected helper. |
| `stage_core.py` | `3af37cbc0169c91ac92b0c8ddc08702690df247aa6954ba2f54693bc46e7ac35` | Matches preceding verified identity. |
| `check_ac17.py` | `25f8d2e051b30027612303d07ce02c8daeb7878966a46b01936b2eba0f3bd0c2` | Matches preceding identity recorded before this round. |

### Checklist Results

| Check | Result | Observation |
|---|---|---|
| PR-6 correction readiness | fail | Named raw census and per-hit disposition log absent for the F-013 correction. This is the sole refusal reason. |
| DR-1 / DR-5 / DR-7 receipt identities | pass, limited | All seven file hashes match; complete named Pester receipts inspected. Receipt identity does not independently prove script correctness or the planner's recorded exits. |
| Loop identity and admissibility | pass | Live ledger reports producer `claude-opus-coordinator`, reviewer `gpt-6.1-sol`, rounds 5/8, tokens 29,034,117/150,000,000, next reserve 5,568,458, and `NEXT ROUND: permitted`. Mechanism relief remains recorded. No ledger mutation performed. |
| PR-1–PR-5 / PR-7–PR-9; substantive DR checks | n/a this round | Not assessed after the mandatory procedural stop; prior findings and conclusions are preserved without reasserting them. |

~~~json
{"schema_version":"evidence.v1","check_id":"r6-pr6-and-identities","command":"rtk proxy python -B -X utf8 C:/Temp/agentic-framework/receipts/rl-r6-audit.py","exit_code":0,"result":"fail","phase":"static","scope":"PR-6 before corrected-content review; file identity only","tested_state":"implementation-plan.md 8344b78fcbdd6921caa051eecbedb3c1b7527c6cfe28d58881c3ec0b3e0c4fc6; task.md d35047411b01b449cba0bc05149125320423934ddd96afe0ab56315192d825d3; run_pester.ps1 69940ba77e1943ce4df4dea07f5e96b8591c3e24f761c80adc943f6e23146535","output":"Audit driver completed with exit 0. Seven expected SHA-256 values matched. No census/disposition mentions in the complete latest correction section or implementation-plan.md; task.md matches are three future deliverable labels. Named directory holds seven receipts: credits-stage.txt, f013-missing.txt, full-pytest.txt, lint-set.txt, pester-stage-r5.txt, pester-stage.txt, stage.txt. PR-6 fails; substantive probes not run."}
~~~

~~~json
{"schema_version":"evidence.v1","check_id":"r6-correction-evidence-manual","command":null,"procedure":"Read the complete Corrections Applied — Round 5 F-013 section and both named Pester receipts; compare their purposes with PR-6 and plan-corrections Step 5c; inspect all references for a named raw census and per-hit dispositions.","observer":"gpt-6.1-sol","exit_code":null,"result":"fail","phase":"manual","scope":"PR-6 correction evidence","output":"Correction table gives finding-level changes, test observations and hashes. Neither the raw old/new-value census nor per-hit file:line dispositions is supplied. Pester outputs are test-run receipts, not census output. Both receipt hashes match, and their first self-check lines precede the real-run summaries; this textual observation is not a code-order probe."}
~~~

~~~json
{"schema_version":"evidence.v1","check_id":"r6-ledger-state","command":"rtk proxy python -B -X utf8 core/tools/review_ledger.py state --loop-id review-limits-parameters-plan-2026-10-20","exit_code":0,"result":"pass","phase":"static","scope":"review-round permission and identity","tested_state":"live ledger before Round 6 is recorded","output":"rounds 5/8; tokens 29,034,117/150,000,000 spent; next reserve 5,568,458; producer claude-opus-coordinator; preceding reviewer gpt-6.1-sol; task-row-completion-predicate RELIEVED; scaffolding 0/2; NEXT ROUND: permitted."}
~~~

### Verdict and Follow-up

**changes_required** — F-014 is the sole blocking procedural finding. **Intent achieved: partial**: acceptance is withheld because required correction evidence is missing; no claim is made that the product intent itself has regressed. Supply the F-013 census receipt and per-hit dispositions through `/plan-corrections` before another authorized review. The human's grant permits Round 6 of 8 and 150M total tokens; the old correction-log statement that an additional grant is needed is historical and is not a blocker.

Canonical output: `.agent/context/handoffs/2026-10-20-review-limits-parameters-plan-critical-review.md`. Pre-Edit Guard resolves exactly to this file. This Round 6 section is appended; all preceding bytes remain intact. Reviewer audit/stamp receipts are external. No plan, product, tool or repository test is edited, no commit is created, and no corrections or implementation workflow is started. The final chat response follows the explicitly requested v2 JSON format; the completion stamp is embedded here.

🕐 Completed: 2026-10-20 21:03 (EDT)

## Corrections Applied — Round 6 F-014 (planner, 2026-10-20, after round 6)

**Ledger state.** Round 6 is recorded as returned (`changes_required`, 1 blocking, usage 1,199,640); next round permitted, 6/8 used. The human's grant before round 6: "add 3 more rounds and increase token limit to 150M total" (ledger `continue` by MatBanik at 2026-10-20T21:01:17-04:00, +3 rounds, +118,500,000 tokens).

**F-014 accepted.** The round-5 correction log had no blast-radius census. That was a planner omission. The census below covers the F-013 change.

**One further plan edit, made before this census.** Plan §3's self-check list now also says the script "passes a passing directory named in other letter case (Pester reports the on-disk case)", to match the self-check case added in round 5. No other plan, task or script change since the round-5 log.

**Census (Step 5c).** Receipt: `C:/Temp/agentic-framework/receipts/census-rl-r5/census-review-limits-r5.txt` (sha256 `1e5eff388959e955978bf34ce7f44e4a0a2ca53a37b866e2c87ec3ff31be28bf`), 118 lines, untruncated. It holds 21 sweeps (`rg -F -n` over implementation-plan.md, task.md and run_pester.ps1). Old value, then new value, then semantic variants of the coverage predicate: `F-013`, `requested path`, `requested suite`, `missing`, `yields`, `discovered`, `no test file`, `a file with no test`, `letter case`, `Uncovered`, `Get-UncoveredPath`, `OrdinalIgnoreCase`, `Test-Paths`, `pre-existing`, `Start-CreditsRun.Tests.ps1`, `Register-CreditsRun.Tests.ps1`, `run_pester`, `Result=Passed`, `` is `Passed` ``, `FailedCount`, `self-check`. Three end `# rg exit 1`: `requested suite` (unused phrasing), `pre-existing` (the round-5 residue is gone) and `Result=Passed` (the script prints `Result={1}`, a format slot). There are 50 unique `file:line` hits.

| Hits | Disposition |
|---|---|
| run_pester.ps1:6, 7, 8, 12, 13, 17, 18, 21, 32, 35, 36, 43, 57, 59, 90, 91, 92, 95, 101, 108, 109, 111, 112 (23 hits) | updated: the F-013 script change. `.DESCRIPTION` text, the coverage rule and its case-insensitive prefix test, `Test-Paths`, the self-check cases, and the `Uncovered` report and verdict. |
| implementation-plan.md:233 (AC-21 row) | updated: the (g) negative check names the requested-path refusal with the Start/Register example, and sources gain round 5, F-013. (a)–(f) unchanged. |
| implementation-plan.md:362–369 | updated: the §3 Pester bullet (requested-path rule, F-013) and the self-check list, including the letter-case pass case added above. |
| implementation-plan.md:365 | confirmed-consistent: the `FailedCount` hit is the prose explaining why that count alone is not trusted. |
| implementation-plan.md:373; task.md:40, 54, 56 | confirmed-consistent: the §3 Pester command and rows 0, 7a, 7c call `run_pester.ps1` with explicit paths, which the coverage rule now checks. No command change is needed. Row 7a's two named files are the F-013 case, and both must now be discovered. |
| implementation-plan.md:282 | confirmed-consistent: the Files Modified row for the two Pester files (AC-21 (f)). |
| implementation-plan.md:6, 105, 111, 201, 202, 217, 225, 227, 443, 465, 471; task.md:15, 44, 99 | confirmed-consistent: `missing` or `yields` in unrelated senses (`policy_missing`, a missing key or ledger, a missing dependency, "yields" in AC-5). None concerns the Pester gate. |

**Edge probes, run before dispatch** (scratch fixtures, console only; each run also passed the self-check first). Refused, exit 1: an empty `tests` beside a passing sibling `tests2`, and an empty directory beside a passing file. Passed, exit 0: the passing directory given with a trailing slash, with backslashes, relative to the working directory, and twice.

**Plan-file hashes at this point.** implementation-plan.md `47add9ad30ad8d0b13f1cd4ca12a55c21053dc76da5c689a93f28618aba47155`; task.md `d35047411b01b449cba0bc05149125320423934ddd96afe0ab56315192d825d3`; run_pester.ps1 `69940ba77e1943ce4df4dea07f5e96b8591c3e24f761c80adc943f6e23146535`; stage_core.py `3af37cbc0169c91ac92b0c8ddc08702690df247aa6954ba2f54693bc46e7ac35`; check_ac17.py `25f8d2e051b30027612303d07ce02c8daeb7878966a46b01936b2eba0f3bd0c2`. The round-5 receipts (`f013-missing.txt`, `pester-stage-r5.txt`) were produced by this same run_pester.ps1 hash.

**Next step.** Round 7 (7 of 8).


## Recheck (2026-10-20) — Round 7

**Workflow:** `/plan-critical-review` · **Agent:** `gpt-6.1-sol` (live dispatch registry) · **Requested verbosity:** standard
**Loop:** `review-limits-parameters-plan-2026-10-20` · **Verdict:** `approved` · **Intent achieved:** `yes` (plan readiness; implementation remains unstarted).

**Intent anchor:** "Make review round caps and token budgets setup choices in the repo, adopted by each plan and execution as tighten-only defaults, with loosening only through a verified human-typed offer."

### Findings

No new findings or remaining blocking items. The corrected coverage gate refused every requested negative path case. Executing WP-1–WP-5 as specified would deliver the registered goal and the human-approved D-1 extension.

### Prior Pass Summary and Confirmed Fixes

| Finding | Prior status | Round 7 result |
|---|---|---|
| F-014 — correction census absent | open, blocking in Round 6 | **Fixed.** The named receipt is untruncated, its hash matches, all 21 sweeps reproduce against the live files, and all 50 unique hits have explicit dispositions. |
| F-013 — a requested Pester path may be silently omitted | corrected, substantive recheck withheld in Round 6 | **Fixed.** Missing-file and empty-directory requests beside a passing file refuse with `Result=Passed`, `Passed=1`, `Uncovered=1`, exit 1. The prefix sibling also refuses; discovery failures refuse through the independent outcome predicate. |
| F-008 / F-010 — non-passing Pester outcome / interrupted pytest accepted | corrected in Round 4 | **Still fixed.** Pester requires `Result=Passed`, positive passing count, and zero failed tests, blocks and containers. Pytest's status is captured immediately and propagated; no failure comparison survives. |
| F-011 / F-012 — baseline identity alias / task lint refusal | retired / corrected in Round 4 | **Still resolved.** `new_failures.py` and the Pester baseline mode are absent. Fresh task lint with `RECEIPTS_DIR` set passes. |

### Scope and PR-6 — Verified First

Reviewed both plan carriers, `run_pester.ps1`, `stage_core.py`, unchanged `check_ac17.py`, the corrections and earlier findings, and the cited ledger, authorization, instantiate and credits entrypoints. All 39 task rows remain unchecked and the project implementation handoff is absent. The `in_progress` task frontmatter does not establish implementation.

The census receipt named in the latest correction log has SHA-256 `1e5eff388959e955978bf34ce7f44e4a0a2ca53a37b866e2c87ec3ff31be28bf`. Its 118 lines contain 21 complete sweep/exit pairs and 50 unique `file:line` hits. Fresh unfiltered `rg -F -n` sweeps reproduce every hit's current text and each exit code; there is no undispositioned hit. The disposition range `implementation-plan.md:362–369` also includes a non-hit line, which does not omit or obscure any hit. The disclosed section-3 letter-case wording edit is present before the census; no subsequent mismatch exists. **PR-6 passes.**

| Reviewed artifact | SHA-256 |
|---|---|
| `implementation-plan.md` | `47add9ad30ad8d0b13f1cd4ca12a55c21053dc76da5c689a93f28618aba47155` |
| `task.md` | `d35047411b01b449cba0bc05149125320423934ddd96afe0ab56315192d825d3` |
| `run_pester.ps1` | `69940ba77e1943ce4df4dea07f5e96b8591c3e24f761c80adc943f6e23146535` |
| `stage_core.py` | `3af37cbc0169c91ac92b0c8ddc08702690df247aa6954ba2f54693bc46e7ac35` |
| `check_ac17.py` | `25f8d2e051b30027612303d07ce02c8daeb7878966a46b01936b2eba0f3bd0c2` |

### Substantive F-013 Recheck

The helper normalizes requested paths with `Resolve-Path` and `GetFullPath`, trims trailing separators, and matches a discovered container file either by equality or by a directory prefix ending in the separator (`run_pester.ps1:35–46`). `OrdinalIgnoreCase` handles Windows case differences without admitting a `tests2` sibling for `tests`. A path missing from disk is immediately uncovered. The final gate combines this predicate with `Test-Gate` (`:107–114`).

The complete nine-case self-check executes before the real `Invoke-Run` (`:83–108`). Each real probe below printed the successful self-check before real discovery. The discovery-failing directory is correctly covered as a discovered file, but the failed container independently refuses the run: coverage is not being mistaken for successful execution.

| Fresh probe | Actual exit | Decisive real-run result |
|---|---|---|
| Passing file | 0 | `PASS: Result=Passed Passed=1 ... Uncovered=0` |
| Missing file beside passing file | 1 | Missing request printed; `FAIL: Result=Passed Passed=1 ... Uncovered=1` |
| Empty directory beside passing file | 1 | Empty directory printed; `FAIL: Result=Passed Passed=1 ... Uncovered=1` |
| Directory whose only test file fails discovery, beside passing file | 1 | `FAIL: Result=Failed Passed=1 Failed=0 FailedBlocks=0 FailedContainers=1 ... Uncovered=0` |
| Passing directory with trailing slash | 0 | `PASS ... Uncovered=0` |
| Passing directory with backslashes | 0 | `PASS ... Uncovered=0` |
| Passing directory in other letter case | 0 | `PASS ... Uncovered=0` |
| Working-directory-relative `./good` | 0 | `PASS ... Uncovered=0` |
| Empty `tests` beside passing sibling `tests2` | 1 | `tests` printed; `FAIL: Result=Passed Passed=1 ... Uncovered=1` |
| Same passing directory requested twice | 0 | `PASS ... Uncovered=0`; duplicate requests do not falsely become uncovered |

**The new self-check cases exercise their intended code.** Running the actual extracted functions against real Pester results gives `Test-Gate=true` for both the missing-file and bare-directory pairs; each has exactly its absent/empty request uncovered, so the combined check returns false because of the new coverage predicate. For the differently cased directory, Pester reports the on-disk case and the combined check is true. Changing only `OrdinalIgnoreCase` to `Ordinal` in a scratch copy makes that same case uncovered and false. The repository helper was never changed.

**Environment qualification.** The unchanged helper with default Pester settings exits 1 at its first all-passing self-check in this sandbox. A direct Pester diagnostic identifies `System.Security.SecurityException: Requested registry access is not allowed` when creating `HKEY_CURRENT_USER\Software\Pester`. The probes therefore set only `$global:PesterPreference=@{TestRegistry=@{Enabled=$false}}`, then invoke the unchanged helper and propagate its `$LASTEXITCODE`. Assertions, discovery, outcome counters, path coverage and all nine self-check cases remain active. These fixtures use no registry. This is fresh targeted evidence under that configuration, not a fresh pass of the full production Pester suite. The same sandbox limitation was disclosed in Round 4.

Two reviewer-driver errors were corrected before accepting evidence: the first forwarding wrapper failed to propagate the child script's exit, and the support audit initially counted the status-legend row as a task. Those failed audit results are discarded; neither is a plan/helper defect. Final observations below use the corrected drivers and actual child exits.

### Plan Wiring, Round-4 Corrections and WP Substance

- **Rows 0, 7a, 7c and section 3:** row 0 invokes the whole staged tests directory after the prerequisite identity checks, full pytest and staged credits pytest; it stops at the first nonzero status. Row 7a stages afresh and passes both `Start-CreditsRun.Tests.ps1` and `Register-CreditsRun.Tests.ps1` explicitly. Row 7c stages afresh, captures pytest's status before `Pop-Location`, stops on nonzero, then invokes the whole staged Pester directory. Section 3 uses the same helper. Every Pester call saves and re-raises its exit. The coverage correction therefore reaches all intended gates (`task.md:40,54,56`; `implementation-plan.md:352–380`).
- **AC-21(g):** the negative check at `implementation-plan.md:233` matches the implementation: assertion, discovery, setup, teardown, no-test and missing-request refusals are in the self-check; interrupted pytest cannot pass the exit-0-only rule. The self-check also covers a bare directory and a case-insensitive positive directory. No baseline comparison or exception remains.
- **Round 4:** `psutil` imports as 7.2.2 in Python 3.14.7; the session registry is `P:/.agent`. `new_failures.py`, `-Baseline`, `FailuresOut` and the retired comparison wording remain absent from the live plan/task/helper. Fresh lint reports 39 rows, 37 fully checked, two view-file exemptions and acyclic dependencies. Historical baseline receipts retain their declared SHA-256 values and report 476 staged credits tests passed (50 skipped), 2072 full pytest tests passed (36 subtests), and 324 Pester tests passed with zero failure counters. These are verified historical planner observations, not new suite runs or execution row 0.
- **Staging and AC-17:** `stage_core.py` still copies the working tree's `core/`, fills through the real instantiate entrypoint and verifies the result. Fresh subprocess injections return fill exit 7 without verify, and verify exit 8 after a successful fill. A real receipts-local stage with only its two output constants overridden in memory fills and verifies with zero placeholders. The unchanged AC-17 oracle exits 1 with 27 problems both at its fixed baseline and in the unstarted tree, the expected pre-WP-4 red result.
- **WP-1 / AC-1–AC-4:** repo configuration, shipped-default equality, setup flags/config precedence, no-write usage refusals and read-only verify are still concrete deliverables.
- **WP-2 / AC-5–AC-12:** repo → plan → tighten-only flags, explicit `off`, provenance, strict invalid-input refusals, unchanged other stops and legacy-ledger compatibility remain specified and tested through the planned production `begin` path.
- **WP-3 / AC-13–AC-16:** loosening still requires the verified human-typed self-contained offer, with negative cases for bare acceptance, disabled authorization and mismatched limits. Final audit reads execution-ledger `rounds_allowed()` including continuations; missing or malformed state fails closed. The read-only verifier and offer-version migration remain included.
- **WP-4 / AC-17–AC-20:** both carriers, source-attributed cap prose, setup questions, version bumps, manifest entry and the bounded AC-17 inventory plus in-place editorial review remain in scope.
- **WP-5 / AC-21(a–g):** omitted caps require repo `off`, present caps still bind, admissions recheck the switch, uncapped launch passes zero explicitly rather than falling into the manual $2 default, and exposure/chain-room semantics remain specified. The schema, launcher, registration tests and skill text remain scheduled. Human decisions D-1/D-2 are preserved. No scope has been silently dropped.

### Checklist Results

| Check | Result | Evidence |
|---|---|---|
| PR-1 / PR-2 / PR-3 | pass | Plan/task work and dependencies align; 39 unchecked rows; implementation handoff absent; task linter passes with configured receipts. |
| PR-4 / PR-8 / DR-4 | pass within requested recheck | Ten actual path probes, nine-case self-check before every real run, direct coverage isolation, case-sensitive negative mutation and stage fail-fast probes behave as specified. |
| PR-5 / PR-7 / PR-9 | pass | AC source labels and D-1/D-2 are retained; exclusions respect the requested modes and manual runner boundary; shared shapes remain authoritative. |
| PR-6 / DR-1 / DR-5 / DR-7 | pass | Census identity, every live hit and per-hit disposition verified first; corrected file hashes and baseline receipt identities match. |
| DR-2 / DR-3 / DR-6 / DR-8 | pass | Retired comparison paths remain absent; all call sites use the corrected helper; no implementation-complete claim is made. |
| Fresh complete production suites | not_run | This is an unstarted-plan recheck. Historical baseline receipts are audited separately; default Pester registry setup is denied by this sandbox. Execution row 0 still requires fresh green baselines. |

```json
{"schema_version":"evidence.v1","check_id":"r7-pr6","command":"rtk proxy python -B -X utf8 C:/Temp/agentic-framework/receipts/rl-r7-census.py","exit_code":0,"result":"pass","phase":"static","scope":"PR-6 before substantive recheck","tested_state":"plan 47add9ad30ad8d0b13f1cd4ca12a55c21053dc76da5c689a93f28618aba47155; task d35047411b01b449cba0bc05149125320423934ddd96afe0ab56315192d825d3; helper 69940ba77e1943ce4df4dea07f5e96b8591c3e24f761c80adc943f6e23146535","output":"21 live sweeps exactly reproduce complete receipt hit lines and exit codes; 118 lines; 50 unique hits; all dispositioned; census sha256 1e5eff388959e955978bf34ce7f44e4a0a2ca53a37b866e2c87ec3ff31be28bf; all five target hashes match."}
```

```json
{"schema_version":"evidence.v1","check_id":"r7-path-probes","command":"rtk proxy python -B -X utf8 C:/Temp/agentic-framework/receipts/rl-r7-probes.py","exit_code":0,"result":"pass","phase":"targeted","scope":"AC-21(g), requested path coverage and self-check reachability; real Pester 5.7.1 with TestRegistry disabled","tested_state":"run_pester.ps1 69940ba77e1943ce4df4dea07f5e96b8591c3e24f761c80adc943f6e23146535","output":"Ten path probes match expected exits: pass 0; missing 1; bare 1; discovery-failing directory 1; trailing slash 0; backslashes 0; other case 0; relative 0; tests/tests2 prefix 1; duplicate 0. Every self-check precedes real discovery. Missing/bare direct runs have Test-Gate=true, Uncovered=1, Combined=false. Other-case Combined=true; Ordinal-only scratch mutant Combined=false."}
```

```json
{"schema_version":"evidence.v1","check_id":"r7-support","command":"rtk proxy python -B -X utf8 C:/Temp/agentic-framework/receipts/rl-r7-support.py --followup","exit_code":0,"result":"pass","phase":"targeted","scope":"stage helper, historical baseline identity, retired comparison gates, readiness and AC-17 oracle","tested_state":"stage_core.py 3af37cbc0169c91ac92b0c8ddc08702690df247aa6954ba2f54693bc46e7ac35; check_ac17.py 25f8d2e051b30027612303d07ce02c8daeb7878966a46b01936b2eba0f3bd0c2; unchanged product diff","output":"Fill failure 7 propagates with one call; verify failure 8 propagates with two calls; real fill/verify exit 0, zero placeholders. Historical credits/full-pytest/Pester hashes match and report 476/2072/324 passed. Plain gates retained; 39 unchecked rows; implementation handoff absent. Product git diff exit 0. AC-17 child exit 1, 27 baseline and 27 working-tree problems as expected before implementation."}
```

```json
{"schema_version":"evidence.v1","check_id":"r7-task-lint","command":"rtk proxy python -B core/tools/lint_task_contract.py --task docs/execution/plans/2026-10-20-review-limits-parameters/task.md","exit_code":0,"result":"pass","phase":"static","scope":"task contract with RECEIPTS_DIR set","tested_state":"task.md d35047411b01b449cba0bc05149125320423934ddd96afe0ab56315192d825d3","output":"OK: 39 row(s); 10-column table; 37 fully checked; dependencies resolve and are acyclic; 2 view_file exemptions H1-5, H2-1."}
```

```json
{"schema_version":"evidence.v1","check_id":"r7-substance","procedure":"Read all AC-1 through AC-21, the task rows, shared contracts, file inventory and exclusions; trace planned setup, ledger, authorization/audit and credits changes against their named current production entrypoints; inspect every corrected gate call and immediate exit capture; compare with D-1/D-2 and the registered goal.","observer":"gpt-6.1-sol","exit_code":null,"result":"pass","phase":"manual","scope":"WP-1 through WP-5 and row 0/7a/7c/section-3 gate wiring","output":"The specified work delivers setup choices and inherited tighten-only plan/execution limits with verified human-typed loosening, plus the approved optional scheduled credits caps. Required deliverables and negative cases remain present. No new delivery blocker found."}
```

### Verdict, Follow-up and Limits

**approved** — F-014 and F-013 are resolved; no blocking finding remains. **Intent achieved: yes** means the plan is ready to deliver the requested behavior when executed. Product implementation and its acceptance tests remain future work.

Read-only ledger state before this verdict reports producer `claude-opus-coordinator`, reviewer `gpt-6.1-sol`, rounds 6/8, tokens 30,233,757/150,000,000 and `NEXT ROUND: permitted`; the mechanism relief remains recorded. This is Round 7 of 8. The dispatch wrapper records this returned verdict; the reviewer has not mutated the ledger. No additional review/correction or execution workflow is started here. The earlier human execution authorization is acknowledged and does not require repetition from this review.

Residual risk: a fresh complete product/Pester run was not performed in this reviewer sandbox. The audited historical baselines do not complete execution row 0; that row still requires fresh green full pytest, staged credits pytest and staged Pester results under the documented prerequisites. No unresolved product decision or correction is required by this review.

Canonical output: `.agent/context/handoffs/2026-10-20-review-limits-parameters-plan-critical-review.md`. Pre-Edit Guard resolves exactly to that path. This section is appended and all earlier bytes/frontmatter are preserved. The only repository write is this rolling review; fixtures, audit drivers and receipts are external. No plan, product, helper, tool or repository test is edited and no git commit is created. The completion stamp is embedded here to preserve the requested final v2 JSON format.

🕐 Completed: 2026-10-20 21:13 (EDT)
