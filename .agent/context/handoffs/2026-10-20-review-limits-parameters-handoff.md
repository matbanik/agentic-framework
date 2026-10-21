---
date: "2026-10-20"
project: "review-limits-parameters"
meus: []
status: "in_progress"
action_required: "VALIDATE_AND_APPROVE"
template_version: "2.2"
verbosity: "standard"
plan_source: "docs/execution/plans/2026-10-20-review-limits-parameters/implementation-plan.md"
agent: "implementing agent"
reviewer: "codex (cli-dispatch, execution mode, ledger loop exec-2026-10-20-review-limits-parameters)"
predecessor: "2026-10-20-review-limits-parameters-plan-critical-review.md"
---

# Handoff: 2026-10-20-review-limits-parameters-handoff

> **Status**: `in_progress` (implementation and verification done; the execution review is pending)
> **Action Required**: `VALIDATE_AND_APPROVE`

---

## Scope

**MEU**: none (`meus: []`). The plan came straight from a user request.

**What changed:** the review loops' round and token budgets are now a repository setup choice
with per-plan parameters:

- `core/.agent/review-limits.json` ships the current defaults (plan 3, execution 6, and the
  `TOKEN_BUDGETS` constants, `token_budgets: "on"`).
- `scripts/instantiate.py --round-caps` / `--token-budgets` (ADOPTION-QUESTIONS B5/B5b) write it.
- `review_ledger.py begin` resolves the limits in one order: the repo file, then the plan's
  `review_limits` block, then flags that only tighten. A `basis: loosened` block counts only
  after `run_parameters.py limits-check` verifies a human-typed `run-parameters-offer/2`.
- `token_budgets: "off"` also lifts the USD caps of scheduled credits runs (D-1).

**Not in scope:** the plan's §Out of Scope table (manual runner's $2 default, grouping line,
other modes' plan blocks, `MECHANISM_LIMIT`/`SCAFFOLDING_CAP`, the diagram, policy pinning).

**Predecessor:** the plan review, approved at round 7:
[2026-10-20-review-limits-parameters-plan-critical-review.md](2026-10-20-review-limits-parameters-plan-critical-review.md).

No commit and no push were made. H2-5 drafts the commit for the human.

---

## Acceptance Criteria

| AC | Type | Description | Source | Test(s) | Status |
|----|------|-------------|--------|---------|--------|
| AC-1 | unit | The shipped `review-limits.json` equals `ROUND_BUDGETS`/`TOKEN_BUDGETS`, with `token_budgets: "on"` | Spec | `scripts/tests/test_instantiate_review_limits.py`: `test_shipped_file_equals_constants`, `test_reader_accepts_the_repo_file` | ✅ |
| AC-2 | integration | `--round-caps` / `--token-budgets` and the config keys write the file; a flag beats the config; bad answers exit 2 and write nothing | Spec; Local Canon | `test_instantiate_review_limits.py`: `test_flags_write_the_answers`, `test_config_answers_give_the_same_bytes`, `test_flag_beats_config`, `test_run_takes_the_answers`, `test_a_bad_answer_exits_2`, `test_a_bad_config_answer_exits_2` | ✅ |
| AC-3 | integration | No answer leaves the file byte-identical | Local Canon | `test_instantiate_review_limits.py`: `test_no_answer_keeps_the_file_identical` | ✅ |
| AC-4 | unit | `--verify` fails a file that `load_repo_limits` refuses, and writes nothing | Local Canon | `test_instantiate_review_limits.py`: `test_verify_accepts_an_untouched_file`, `test_verify_refuses_a_bad_file` | ✅ |
| AC-5 | integration | `begin` uses the repo values; `source=repo:<sha12>` | Spec | `core/tools/tests/test_review_limits.py`: `test_repo_file_sets_the_limits`, `test_repo_switch_off_opens_an_unbudgeted_loop` | ✅ |
| AC-6 | integration | No file → constants; a malformed file → exit 3 | Local Canon | `test_review_limits.py`: `test_no_repo_file_uses_the_constants`, `test_malformed_repo_file_fails_closed`, `test_repo_value_of_zero_fails_closed` | ✅ |
| AC-7 | integration | The plan's `review_limits` block for plan/execution loops; basis mismatch or malformed → exit 3 | Spec | `test_review_limits.py`: `test_block_at_basis_repo_names_the_plan`, `test_tightened_block_sets_the_mode_values`, `test_other_modes_ignore_the_block`, `test_basis_mismatch_fails_closed`, `test_malformed_block_fails_closed`, `test_loosened_block_needs_limits_check` | ✅ |
| AC-8 | integration | The sibling `task.md` block must equal the plan block | Local Canon | `test_review_limits.py`: `test_equal_task_block_is_accepted`, `test_task_without_a_block_is_accepted`, `test_unequal_task_block_is_refused` | ✅ |
| AC-9 | integration | `--round-budget` / `--token-budget N\|off` only tighten | Human-approved (D-2) | `test_review_limits.py`: `test_tightening_flags_are_recorded`, `test_loosening_flag_is_refused`, `test_flag_applies_after_the_plan_block`, `test_token_flag_under_repo_off`, `test_bad_flag_value_is_a_usage_error` | ✅ |
| AC-10 | unit | `"off"` token budget: no tokens stop, `state` says off, `continue --tokens` exit 1, 0/null → exit 3 | Spec | `test_review_limits.py`: `test_off_loop_has_no_tokens_stop`, `test_off_loop_reserve_does_not_divide`, `test_off_loop_readout_says_off`, `test_numeric_budget_of_one_still_stops`, `test_continue_tokens_on_an_off_loop_is_refused`, `test_hand_edited_bad_budget_fails_closed` | ✅ |
| AC-11 | unit | Other stops unchanged; selftest ≥ 115 arms, all pass | Local Canon | `test_review_limits.py`: `test_selftest_passes_with_at_least_115_arms`; `review_ledger.py selftest` (125 arms) | ✅ |
| AC-12 | unit | A pre-change ledger behaves as before | Local Canon | `test_review_limits.py`: `test_legacy_ledger_gives_the_same_stops`, `test_legacy_ledger_state_and_continue` | ✅ |
| AC-13 | integration | `basis: loosened` only after `limits-check` verifies a self-contained, human-typed /2 offer | Human-approved (D-2) | `core/tools/tests/test_review_limits_audit.py`: `test_human_typed_offer_passes_limits_check`, `test_begin_opens_a_loosened_loop_after_limits_check`, `test_limits_check_refuses`, `test_begin_exits_1_when_limits_check_refuses`, `test_begin_refuses_a_same_slug_ac_file_with_other_limits`, `test_limits_check_refuses_off_windows` | ✅ |
| AC-14 | unit | Offer schema /2 with `review_limits`; /1 cannot carry it | Local Canon | `test_review_limits_audit.py`: `test_v2_offer_parses_typed_limits`, `test_v1_offer_cannot_carry_review_limits`, `test_v2_offer_refuses_a_quoted_round_count`, `test_v2_schema_file_matches_the_parser` | ✅ |
| AC-15 | integration | The final audit's execution cap comes from `audit_round_cap` (ledger first, fail-closed) | Local Canon | `test_review_limits_audit.py`: `test_audit_cap_counts_a_continue_grant`, `test_audit_cap_without_a_grant_stops_round_7`, `test_audit_cap_refuses_a_block_without_a_ledger`, `test_audit_cap_refuses_a_malformed_ledger`, `test_audit_cap_refuses_a_plan_mode_ledger`, `test_audit_cap_of_a_legacy_task`, `test_the_fixed_cap_is_no_longer_passed_directly` | ✅ |
| AC-16 | unit | `limits-check` is read-only | Local Canon | `test_review_limits_audit.py`: `test_limits_check_writes_nothing`, `test_limits_check_without_a_store_creates_none` | ✅ |
| AC-17 | integration | `create-plan.md` Step 0 and the `FIXED_CAP_INVENTORY` prose name the limit's source | Spec | task rows 5a/5b: `check_ac17.py` (passes now; finds 27 problems at `d698342`) | ✅ |
| AC-18 | unit | PLAN-TEMPLATE 2.4 / TASK-TEMPLATE 2.5 carry the optional block; selftests pass | Local Canon | task rows 5c/5c2; `scripts/tests/test_run_parameters_template.py` | ✅ (row 5c ran as an equivalent script file, D-15) |
| AC-19 | unit | B5/B5b in ADOPTION-QUESTIONS and PROJECT-PROFILE-TEMPLATE | Spec; Human-approved (D-1) | task row 5d grep | ✅ |
| AC-20 | unit | MANIFEST lists the file; `execution-session.md` says where the budgets come from; refcheck 0 unresolved | Local Canon | task rows 5e and 5; `scripts/refcheck.py` | ✅ (needed three pinned refcheck exemptions, D-14) |
| AC-21 | integration | Credits USD caps follow `token_budgets` (a)–(g) | Human-approved (D-1) | (a)–(e) `core/tools/tests/test_credits_uncapped.py` (37 tests); (f) `Start-CreditsRun.Tests.ps1` Describe 'AC-21 (f): an uncapped admission runs with no --max-budget-usd', `Register-CreditsRun.Tests.ps1` Describe 'AC-21 (f): a manifest without caps passes the schema check; credits_state.py decides'; (g) SKILL.md grep, stage credits pytest and every stage Pester suite | ✅ |

<!-- CACHE BOUNDARY -->
<!-- Content above this line is stable across revision passes (KV cache prefix). -->
<!-- Content below this line changes between passes (evidence, results, corrections). -->

---

## Evidence

### FAIL_TO_PASS

| Test | Red Output (hash/snippet) | Green Output | File:Line |
|------|--------------------------|--------------|-----------|
| `test_shipped_file_equals_constants` | FileNotFoundError on `core/.agent/review-limits.json` (`93d02de4…`) | 1 passed (`d2692635…`) | `scripts/tests/test_instantiate_review_limits.py` |
| `test_instantiate_review_limits.py` (22) | 11 failed, 11 passed (`a6395363…`) | 22 passed (`630956e4…`) | `scripts/tests/test_instantiate_review_limits.py` |
| `test_review_limits.py` (58) | 52 failed, 6 passed (`69118def…`) | 58 passed (`5af84903…`) | `core/tools/tests/test_review_limits.py` |
| `test_review_limits_audit.py` (45 at row 4) | 28 failed, 17 passed (`36ca1f4c…`) | 45 passed (`9c4839f3…`) | `core/tools/tests/test_review_limits_audit.py` |
| `test_begin_refuses_a_same_slug_ac_file_with_other_limits` (round-1 F-001) | begin opened budget=999 tokens=off (`a7eb5b1f…`) | 1 passed, with the updated `test_loosened_block_needs_limits_check` (`5eefbc95…`) | `core/tools/tests/test_review_limits_audit.py` |
| `test_credits_uncapped.py` (37) | 24 failed, 13 passed (`5d8264d4…`) | 37 passed (`67834638…`) | `core/tools/tests/test_credits_uncapped.py` |
| AC-21 (f) Pester Describes (6) | 60 passed, 4 failed with the hunks reversed (`216c6528…`) | 64 passed (`389a8e18…`) | `core/tools/tests/Start-CreditsRun.Tests.ps1`, `core/tools/tests/Register-CreditsRun.Tests.ps1` |
| `test_retained_python_tests_collect` | 1 collection error in the non-Windows install (H1-2 run 1) | 4 passed; full suite 2235 passed, 50 warnings, 36 subtests passed in 2030.31s (0:33:50) | `scripts/tests/test_instantiate_credits_nonwin.py` |

The passes before each change are listed in the red records below; each is a case that holds both before and after (AC-12's legacy stops, argparse's own exit 2, the capped credits paths).

### Commands Executed

Every command ran in `P:/agentic-framework` with `RECEIPTS_DIR` and `AGENT_MODEL_REGISTRY_HOME` set. H1-2 run 3 (after the round-1 F-001 fix) ran at state `d1091f81158afe2bbadec72ce9c11dda616dbd123a0ebe18feb877753594b474` (sha256 of `git rev-parse HEAD`, `git status --porcelain` and `sys.version`; Python 3.14.7); the state was the same before and after the run.

| Check | Exit Code | Key Output |
|-------|-----------|------------|
| `row1-red` | 1 | test_shipped_file_equals_constants: FileNotFoundError on core/.agent/review-limits.json (1 failed, 21 deselected) |
| `row1-green` | 0 | 1 passed, 21 deselected |
| `row2-red` | 1 | 11 failed, 11 passed (the passes: argparse unknown-flag exit 2 cases, the no-answer identity, verify-OK) |
| `row2-green` | 0 | 22 passed |
| `row3-red` | 1 | 52 failed, 6 passed (the passes: legacy-stops identity, two accepted sibling-task cases, three argparse bad-flag cases) |
| `row3-green` | 0 | 58 passed |
| `row4-red` | 1 | 28 failed, 17 passed (the passes: six begin exit-1 refusals with no limits-check verb yet, eleven offer_schema refusals) |
| `row4-green` | 0 | 45 passed |
| `row5a-ac17` | 0 | PASS; the same oracle against d698342 finds 27 problems |
| `row7-red` | 1 | 24 failed, 13 passed (the 13 are the unchanged capped paths) |
| `row7-green` | 0 | 37 passed |
| `row7a-red` | 1 | 60 passed, 4 failed: Register '$.launch.segment_cap_usd is required' from the schema; Start: no 'uncapped' in the admitted log line. The argv case passed red (the store already reserves 0) |
| `row7a-green` | 0 | Pester gate PASS, 64 passed, 0 failed |
| `h1-2-run1-full-pytest` | 1 | FAILED scripts/tests/test_instantiate_credits_nonwin.py::test_retained_python_tests_collect — 1327 tests collected, 1 error (the non-Windows install kept test_review_limits_audit.py but removed run_parameters_fixtures); 1 failed, 2233 passed, 36 subtests passed in 2978.50s |
| `h1-2-run1-refcheck` | 1 | UNRESOLVED: 3 — this handoff's file.py-colon-test cells read as paths (lines 51, 55, 63) |
| `f001-red` | 1 | test_begin_refuses_a_same_slug_ac_file_with_other_limits: begin opened 'exec-loop' with budget=999 tokens=off from a same-slug --ac-file outside the repository (1 failed, 45 deselected; transcribed from the console) |
| `f001-green` | 0 | 2 passed, 102 deselected in 2.41s |
| `h1-2-static` | 0 | no output (0 findings) |
| `h1-2-ledger-selftest` | 0 | RESULT: 125 arm(s), 0 failure(s) [62 must-OK arms, so the tool is not refusing everything] |
| `h1-2-targeted` | 0 | 163 passed in 128.25s (0:02:08) |
| `h1-2-instantiate-selftest` | 0 | RESULT: 44 arm(s), 0 failure(s) [44 passing this run; a validator that always raises cannot pass] |
| `h1-2-full-pytest` | 0 | 2235 passed, 50 warnings, 36 subtests passed in 2030.31s (0:33:50) |
| `h1-2-refcheck` | 0 | UNRESOLVED: 0; not-a-promise (exempt): 8; stale exemptions: 0; UNCLASSIFIED: 0 |
| `h1-2-policy` | 0 | Run-parameters policy check (D-20 A): all checks passed |
| `h1-2-task-lint` | 0 | OK: 39 row(s); 10-column table (with builder_model); 37 row(s) fully checked: backticked, exit-code re-raised, receipt under RECEIPTS_DIR; dependencies resolve and are acyclic; 2 row(s) exempt (view_file): H1-5, H2-1 |
| `h1-2-stage` | 0 | verify: OK (0 placeholder tokens remain); stage ready |
| `h1-2-credits-stage` | 0 | 513 passed, 50 skipped, 1560 deselected, 50 warnings in 772.70s (0:12:52) |
| `h1-2-run2-pester` | 1 | H1-2 run 2: Failed=1 of 330: CreditsRun.Job.Tests.ps1:176 'AC-B.7: Stop-CreditsJob ends every member (empty), and after the last handle closes the proof is gone' — Expected 'gone', But was 'unknown'. Passed in run 1; the file is outside this change |
| `h1-2-pester-flake-isolation` | 0 | after H1-2 run 2: run 1 passed=16 failed=0; run 2 passed=16 failed=0; run 3 passed=16 failed=0 |
| `h1-2-pester-noenv-invalid` | 1 | Failed=52 of 330, each one 'the mock started' / mock CLI calls file missing: an operator error (the two env vars that h1-2.ps1 sets were not set), not a code result; the run is discarded and the gate re-run with the env |
| `h1-2-pester` | 0 | Pester gate PASS: Result=Passed Passed=330 Failed=0 FailedBlocks=0 FailedContainers=0 Skipped=0 Uncovered=0 (H1-2 run 3, after the F-001 fix) |

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row1-red",
  "cwd": "P:/agentic-framework",
  "scope": "AC-1",
  "phase": "red",
  "result": "fail",
  "exit_code": 1,
  "tested_state": "working tree at the task row (HEAD e667fb6 plus the rows done so far; before H1-2)",
  "command": "$env:RECEIPTS_DIR='C:/Temp/agentic-framework/receipts'; $env:AGENT_MODEL_REGISTRY_HOME='P:/.agent'; python -m pytest scripts/tests/test_instantiate_review_limits.py -q -k shipped",
  "output": "test_shipped_file_equals_constants: FileNotFoundError on core/.agent/review-limits.json (1 failed, 21 deselected)",
  "receipt_sha256": "93d02de462942244f0c3468b8c5c30fbd4d1ac963ed8df16d5bda72b0a0b46c8"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row1-green",
  "cwd": "P:/agentic-framework",
  "scope": "AC-1",
  "phase": "green",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "working tree at the task row (HEAD e667fb6 plus the rows done so far; before H1-2)",
  "command": "$env:RECEIPTS_DIR='C:/Temp/agentic-framework/receipts'; $env:AGENT_MODEL_REGISTRY_HOME='P:/.agent'; python -m pytest scripts/tests/test_instantiate_review_limits.py -q -k shipped",
  "output": "1 passed, 21 deselected",
  "receipt_sha256": "d2692635a1fd69e91364f8187526d7c49347239c0033a36a5eefdcfbf20d89ae"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row2-red",
  "cwd": "P:/agentic-framework",
  "scope": "AC-2..AC-4",
  "phase": "red",
  "result": "fail",
  "exit_code": 1,
  "tested_state": "working tree at the task row (HEAD e667fb6 plus the rows done so far; before H1-2)",
  "command": "$env:RECEIPTS_DIR='C:/Temp/agentic-framework/receipts'; $env:AGENT_MODEL_REGISTRY_HOME='P:/.agent'; python -m pytest scripts/tests/test_instantiate_review_limits.py -q",
  "output": "11 failed, 11 passed (the passes: argparse unknown-flag exit 2 cases, the no-answer identity, verify-OK)",
  "receipt_sha256": "a6395363fc814d3bdcbda1da4a2f1fc1bf2c6affa8f45ec81899291010eb91e7"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row2-green",
  "cwd": "P:/agentic-framework",
  "scope": "AC-2..AC-4",
  "phase": "green",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "working tree at the task row (HEAD e667fb6 plus the rows done so far; before H1-2)",
  "command": "$env:RECEIPTS_DIR='C:/Temp/agentic-framework/receipts'; $env:AGENT_MODEL_REGISTRY_HOME='P:/.agent'; python -m pytest scripts/tests/test_instantiate_review_limits.py -q",
  "output": "22 passed",
  "receipt_sha256": "630956e457e4119c7e2e7182bf11166dfbe99d2afbe01fbd2e3080a9b63572c9"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row3-red",
  "cwd": "P:/agentic-framework",
  "scope": "AC-5..AC-12",
  "phase": "red",
  "result": "fail",
  "exit_code": 1,
  "tested_state": "working tree at the task row (HEAD e667fb6 plus the rows done so far; before H1-2)",
  "command": "$env:RECEIPTS_DIR='C:/Temp/agentic-framework/receipts'; $env:AGENT_MODEL_REGISTRY_HOME='P:/.agent'; python -m pytest core/tools/tests/test_review_limits.py -q",
  "output": "52 failed, 6 passed (the passes: legacy-stops identity, two accepted sibling-task cases, three argparse bad-flag cases)",
  "receipt_sha256": "69118def41e668b07be43ab37b1bd8dc2f13c660feb14b2d79fb73e6b2a3f06a"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row3-green",
  "cwd": "P:/agentic-framework",
  "scope": "AC-5..AC-12",
  "phase": "green",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "working tree at the task row (HEAD e667fb6 plus the rows done so far; before H1-2)",
  "command": "$env:RECEIPTS_DIR='C:/Temp/agentic-framework/receipts'; $env:AGENT_MODEL_REGISTRY_HOME='P:/.agent'; python -m pytest core/tools/tests/test_review_limits.py -q",
  "output": "58 passed",
  "receipt_sha256": "5af849031df4e45d6c06e3e44831defda6e2dd37b44eead63d043ce8fda65157"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row4-red",
  "cwd": "P:/agentic-framework",
  "scope": "AC-13..AC-16",
  "phase": "red",
  "result": "fail",
  "exit_code": 1,
  "tested_state": "working tree at the task row (HEAD e667fb6 plus the rows done so far; before H1-2)",
  "command": "$env:RECEIPTS_DIR='C:/Temp/agentic-framework/receipts'; $env:AGENT_MODEL_REGISTRY_HOME='P:/.agent'; python -m pytest core/tools/tests/test_review_limits_audit.py -q",
  "output": "28 failed, 17 passed (the passes: six begin exit-1 refusals with no limits-check verb yet, eleven offer_schema refusals)",
  "receipt_sha256": "36ca1f4caf6e1702b18daf4f996810ddae870536e819c2e0e0e2a767cdedfdb7"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row4-green",
  "cwd": "P:/agentic-framework",
  "scope": "AC-13..AC-16",
  "phase": "green",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "working tree at the task row (HEAD e667fb6 plus the rows done so far; before H1-2)",
  "command": "$env:RECEIPTS_DIR='C:/Temp/agentic-framework/receipts'; $env:AGENT_MODEL_REGISTRY_HOME='P:/.agent'; python -m pytest core/tools/tests/test_review_limits_audit.py -q",
  "output": "45 passed",
  "receipt_sha256": "9c4839f3d328d33a62bd8a7ceea5a4e84284f4287a2eae4288f7fa1daf71013f"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row5a-ac17",
  "cwd": "P:/agentic-framework",
  "scope": "AC-17",
  "phase": "static",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "working tree at the task row (HEAD e667fb6 plus the rows done so far; before H1-2)",
  "command": "$env:RECEIPTS_DIR='C:/Temp/agentic-framework/receipts'; $env:AGENT_MODEL_REGISTRY_HOME='P:/.agent'; python docs/execution/plans/2026-10-20-review-limits-parameters/check_ac17.py",
  "output": "PASS; the same oracle against d698342 finds 27 problems",
  "receipt_sha256": "d6fb293ac2b69da496d52be835dbb294d4db40d1c31781834246849ed48ee13d"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row7-red",
  "cwd": "P:/agentic-framework",
  "scope": "AC-21 (a)-(e)",
  "phase": "red",
  "result": "fail",
  "exit_code": 1,
  "tested_state": "working tree at the task row (HEAD e667fb6 plus the rows done so far; before H1-2)",
  "command": "$env:RECEIPTS_DIR='C:/Temp/agentic-framework/receipts'; $env:AGENT_MODEL_REGISTRY_HOME='P:/.agent'; python -m pytest core/tools/tests/test_credits_uncapped.py -q",
  "output": "24 failed, 13 passed (the 13 are the unchanged capped paths)",
  "receipt_sha256": "5d8264d43d81ba9f9c139c5ac5c0aa0af98561cec703519576aec7a40f96918d"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row7-green",
  "cwd": "P:/agentic-framework",
  "scope": "AC-21 (a)-(e)",
  "phase": "green",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "working tree at the task row (HEAD e667fb6 plus the rows done so far; before H1-2)",
  "command": "$env:RECEIPTS_DIR='C:/Temp/agentic-framework/receipts'; $env:AGENT_MODEL_REGISTRY_HOME='P:/.agent'; python -m pytest core/tools/tests/test_credits_uncapped.py -q",
  "output": "37 passed",
  "receipt_sha256": "67834638becff06e4006af03969e747089387b551841a0ba78ade2e449fa74db"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row7a-red",
  "cwd": "P:/agentic-framework",
  "scope": "AC-21 (f)",
  "phase": "red",
  "result": "fail",
  "exit_code": 1,
  "tested_state": "working tree at the task row (HEAD e667fb6 plus the rows done so far; before H1-2)",
  "command": "$env:RECEIPTS_DIR='C:/Temp/agentic-framework/receipts'; $env:AGENT_MODEL_REGISTRY_HOME='P:/.agent'; row 7a command with the schema and launcher hunks reversed, then restored: run_pester.ps1 <stage>/tools/tests/Start-CreditsRun.Tests.ps1 <stage>/tools/tests/Register-CreditsRun.Tests.ps1",
  "output": "60 passed, 4 failed: Register '$.launch.segment_cap_usd is required' from the schema; Start: no 'uncapped' in the admitted log line. The argv case passed red (the store already reserves 0)",
  "receipt_sha256": "216c652852c832440a121c97f91bb8904e1f0f6691166b60c2fc0e6e32525dd7"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row7a-green",
  "cwd": "P:/agentic-framework",
  "scope": "AC-21 (f)",
  "phase": "green",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "working tree at the task row (HEAD e667fb6 plus the rows done so far; before H1-2)",
  "command": "$env:RECEIPTS_DIR='C:/Temp/agentic-framework/receipts'; $env:AGENT_MODEL_REGISTRY_HOME='P:/.agent'; python docs/execution/plans/2026-10-20-review-limits-parameters/stage_core.py; pwsh -NoProfile -File docs/execution/plans/2026-10-20-review-limits-parameters/run_pester.ps1 C:/Temp/agentic-framework/rl-stage/tools/tests/Start-CreditsRun.Tests.ps1 C:/Temp/agentic-framework/rl-stage/tools/tests/Register-CreditsRun.Tests.ps1",
  "output": "Pester gate PASS, 64 passed, 0 failed",
  "receipt_sha256": "389a8e187af1d35b8d815ebc555ce5474ee1a054b2333680450080f376050da1"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "h1-2-run1-full-pytest",
  "cwd": "P:/agentic-framework",
  "scope": "core/tools/tests + scripts/tests",
  "phase": "full",
  "result": "fail",
  "exit_code": 1,
  "tested_state": "84ae0d929ed1a7c54f5f9fc0fe6c6262e7f9f233041d2ffdff4b5dd4f9d7c154 (before the fix; the identity lists paths, not contents)",
  "command": "$env:RECEIPTS_DIR='C:/Temp/agentic-framework/receipts'; $env:AGENT_MODEL_REGISTRY_HOME='P:/.agent'; python -m pytest core/tools/tests scripts/tests -q -rfE",
  "output": "FAILED scripts/tests/test_instantiate_credits_nonwin.py::test_retained_python_tests_collect — 1327 tests collected, 1 error (the non-Windows install kept test_review_limits_audit.py but removed run_parameters_fixtures); 1 failed, 2233 passed, 36 subtests passed in 2978.50s",
  "receipt_sha256": "995e5da695bb358fc8a3292ad6a8952bdf10a3af923dbbd7dcc2ed28beefb808",
  "fresh": true,
  "snapshot": false
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "h1-2-run1-refcheck",
  "cwd": "P:/agentic-framework",
  "scope": "repository markdown",
  "phase": "static",
  "result": "fail",
  "exit_code": 1,
  "tested_state": "84ae0d929ed1a7c54f5f9fc0fe6c6262e7f9f233041d2ffdff4b5dd4f9d7c154 (before the fix)",
  "command": "$env:RECEIPTS_DIR='C:/Temp/agentic-framework/receipts'; $env:AGENT_MODEL_REGISTRY_HOME='P:/.agent'; python scripts/refcheck.py",
  "output": "UNRESOLVED: 3 — this handoff's file.py-colon-test cells read as paths (lines 51, 55, 63)",
  "receipt_sha256": "eb5964d15f6f9411f1f1f680d9f08afe4c8c526dcc44eb7e856db92c6b3ae79d"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "f001-red",
  "cwd": "P:/agentic-framework",
  "scope": "AC-13",
  "phase": "red",
  "result": "fail",
  "exit_code": 1,
  "tested_state": "84ae0d929ed1a7c54f5f9fc0fe6c6262e7f9f233041d2ffdff4b5dd4f9d7c154 (before the F-001 fix)",
  "command": "$env:RECEIPTS_DIR='C:/Temp/agentic-framework/receipts'; $env:AGENT_MODEL_REGISTRY_HOME='P:/.agent'; Push-Location core; $env:PYTHONDONTWRITEBYTECODE='1'; python -m pytest -p no:cacheprovider -q tools/tests/test_review_limits_audit.py -k same_slug; Pop-Location",
  "output": "test_begin_refuses_a_same_slug_ac_file_with_other_limits: begin opened 'exec-loop' with budget=999 tokens=off from a same-slug --ac-file outside the repository (1 failed, 45 deselected; transcribed from the console)",
  "receipt_sha256": "a7eb5b1fa62a366125cddf2349af58882f243fd04e46998aebf58d596dcbfd4f"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "f001-green",
  "cwd": "P:/agentic-framework",
  "scope": "AC-13",
  "phase": "green",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "d1091f81158afe2bbadec72ce9c11dda616dbd123a0ebe18feb877753594b474",
  "command": "$env:RECEIPTS_DIR='C:/Temp/agentic-framework/receipts'; $env:AGENT_MODEL_REGISTRY_HOME='P:/.agent'; python -m pytest core/tools/tests/test_review_limits_audit.py core/tools/tests/test_review_limits.py -q -k \"same_slug or loosened_block_needs_limits_check\"",
  "output": "2 passed, 102 deselected in 2.41s",
  "receipt_sha256": "5eefbc9525de4f9d111b4c82dc2a7a1d34e551a5ca0032ebda7be44f17047fcf"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "h1-2-static",
  "cwd": "P:/agentic-framework",
  "scope": "the four changed Python modules",
  "phase": "static",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "d1091f81158afe2bbadec72ce9c11dda616dbd123a0ebe18feb877753594b474",
  "command": "$env:RECEIPTS_DIR='C:/Temp/agentic-framework/receipts'; $env:AGENT_MODEL_REGISTRY_HOME='P:/.agent'; python -m pyflakes core/tools/review_ledger.py core/tools/run_parameters.py core/tools/credits_state.py scripts/instantiate.py",
  "output": "no output (0 findings)",
  "receipt_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "h1-2-ledger-selftest",
  "cwd": "P:/agentic-framework",
  "scope": "review_ledger.py",
  "phase": "targeted",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "d1091f81158afe2bbadec72ce9c11dda616dbd123a0ebe18feb877753594b474",
  "command": "$env:RECEIPTS_DIR='C:/Temp/agentic-framework/receipts'; $env:AGENT_MODEL_REGISTRY_HOME='P:/.agent'; python core/tools/review_ledger.py selftest",
  "output": "RESULT: 125 arm(s), 0 failure(s) [62 must-OK arms, so the tool is not refusing everything]",
  "receipt_sha256": "fc7e3034b513eef6180224fcbeae5d0d4bb607bab7dbf4765406090496d9fa34"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "h1-2-targeted",
  "cwd": "P:/agentic-framework",
  "scope": "AC-1..AC-16, AC-21 (a)-(e)",
  "phase": "targeted",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "d1091f81158afe2bbadec72ce9c11dda616dbd123a0ebe18feb877753594b474",
  "command": "$env:RECEIPTS_DIR='C:/Temp/agentic-framework/receipts'; $env:AGENT_MODEL_REGISTRY_HOME='P:/.agent'; python -m pytest core/tools/tests/test_review_limits.py core/tools/tests/test_review_limits_audit.py core/tools/tests/test_credits_uncapped.py scripts/tests/test_instantiate_review_limits.py -q",
  "output": "163 passed in 128.25s (0:02:08)",
  "receipt_sha256": "8779ad0b82645eb7f7541a56c1e093c15bdeee404009f85cbeaef68bfe1aea85"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "h1-2-instantiate-selftest",
  "cwd": "P:/agentic-framework",
  "scope": "scripts/instantiate.py",
  "phase": "targeted",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "d1091f81158afe2bbadec72ce9c11dda616dbd123a0ebe18feb877753594b474",
  "command": "$env:RECEIPTS_DIR='C:/Temp/agentic-framework/receipts'; $env:AGENT_MODEL_REGISTRY_HOME='P:/.agent'; python scripts/instantiate.py --selftest",
  "output": "RESULT: 44 arm(s), 0 failure(s) [44 passing this run; a validator that always raises cannot pass]",
  "receipt_sha256": "922801561e8a7808931f083d4d9e27182eeb4a5de5b161f421a1595a7c4d5ee4"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "h1-2-full-pytest",
  "cwd": "P:/agentic-framework",
  "scope": "core/tools/tests + scripts/tests (baseline 2072 passed)",
  "phase": "full",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "d1091f81158afe2bbadec72ce9c11dda616dbd123a0ebe18feb877753594b474",
  "command": "$env:RECEIPTS_DIR='C:/Temp/agentic-framework/receipts'; $env:AGENT_MODEL_REGISTRY_HOME='P:/.agent'; python -m pytest core/tools/tests scripts/tests -q -rfE",
  "output": "2235 passed, 50 warnings, 36 subtests passed in 2030.31s (0:33:50)",
  "receipt_sha256": "bf043843561c6f38d59430efd3a53a911154c2301f617e0de6a4ef5ea2ea8cb7",
  "fresh": true,
  "snapshot": false
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "h1-2-refcheck",
  "cwd": "P:/agentic-framework",
  "scope": "repository markdown",
  "phase": "static",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "d1091f81158afe2bbadec72ce9c11dda616dbd123a0ebe18feb877753594b474",
  "command": "$env:RECEIPTS_DIR='C:/Temp/agentic-framework/receipts'; $env:AGENT_MODEL_REGISTRY_HOME='P:/.agent'; python scripts/refcheck.py",
  "output": "UNRESOLVED: 0; not-a-promise (exempt): 8; stale exemptions: 0; UNCLASSIFIED: 0",
  "receipt_sha256": "0b8db531be5ca5e0ca97d259679d6981c1c7fa7d0f3e8aa4e4e38b8665948d43"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "h1-2-policy",
  "cwd": "P:/agentic-framework",
  "scope": "run-parameters policy",
  "phase": "static",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "d1091f81158afe2bbadec72ce9c11dda616dbd123a0ebe18feb877753594b474",
  "command": "$env:RECEIPTS_DIR='C:/Temp/agentic-framework/receipts'; $env:AGENT_MODEL_REGISTRY_HOME='P:/.agent'; Push-Location core; python tools/validate_agent_files.py --policy run-parameters; Pop-Location",
  "output": "Run-parameters policy check (D-20 A): all checks passed",
  "receipt_sha256": "66270f2ac79e108ad0396e93093b91b2d3f0a27f52e475fb1487b01b959faa6c"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "h1-2-task-lint",
  "cwd": "P:/agentic-framework",
  "scope": "task.md",
  "phase": "static",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "d1091f81158afe2bbadec72ce9c11dda616dbd123a0ebe18feb877753594b474",
  "command": "$env:RECEIPTS_DIR='C:/Temp/agentic-framework/receipts'; $env:AGENT_MODEL_REGISTRY_HOME='P:/.agent'; python core/tools/lint_task_contract.py --task docs/execution/plans/2026-10-20-review-limits-parameters/task.md",
  "output": "OK: 39 row(s); 10-column table (with builder_model); 37 row(s) fully checked: backticked, exit-code re-raised, receipt under RECEIPTS_DIR; dependencies resolve and are acyclic; 2 row(s) exempt (view_file): H1-5, H2-1",
  "receipt_sha256": "2d33195e096afad1968b04aad0509b2316f6a0f051682c3e31aa36ee543ac1f4"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "h1-2-stage",
  "cwd": "P:/agentic-framework",
  "scope": "staged core install",
  "phase": "runtime",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "d1091f81158afe2bbadec72ce9c11dda616dbd123a0ebe18feb877753594b474",
  "command": "$env:RECEIPTS_DIR='C:/Temp/agentic-framework/receipts'; $env:AGENT_MODEL_REGISTRY_HOME='P:/.agent'; python docs/execution/plans/2026-10-20-review-limits-parameters/stage_core.py",
  "output": "verify: OK (0 placeholder tokens remain); stage ready",
  "receipt_sha256": "b9e431778482c7ba863ce424ef911b993cefb7e5a4d5496ca5edf5a2c811c3c9"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "h1-2-credits-stage",
  "cwd": "P:/agentic-framework",
  "scope": "staged tools/tests -k credits (baseline 476 passed)",
  "phase": "full",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "d1091f81158afe2bbadec72ce9c11dda616dbd123a0ebe18feb877753594b474",
  "command": "$env:RECEIPTS_DIR='C:/Temp/agentic-framework/receipts'; $env:AGENT_MODEL_REGISTRY_HOME='P:/.agent'; Push-Location C:/Temp/agentic-framework/rl-stage; python -m pytest tools/tests -k credits -q -rfE; Pop-Location",
  "output": "513 passed, 50 skipped, 1560 deselected, 50 warnings in 772.70s (0:12:52)",
  "receipt_sha256": "903218c8b25a3ea92b7ea8aeecb00b263bdc42ab7ff5ad876c830045dd162ad5",
  "fresh": true,
  "snapshot": false
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "h1-2-run2-pester",
  "cwd": "P:/agentic-framework",
  "scope": "every staged Pester suite",
  "phase": "full",
  "result": "fail",
  "exit_code": 1,
  "tested_state": "84ae0d929ed1a7c54f5f9fc0fe6c6262e7f9f233041d2ffdff4b5dd4f9d7c154 (H1-2 run 2, before the round-1 F-001 fix; the identity lists paths, not contents)",
  "command": "$env:RECEIPTS_DIR='C:/Temp/agentic-framework/receipts'; $env:AGENT_MODEL_REGISTRY_HOME='P:/.agent'; pwsh -NoProfile -File docs/execution/plans/2026-10-20-review-limits-parameters/run_pester.ps1 C:/Temp/agentic-framework/rl-stage/tools/tests",
  "output": "H1-2 run 2: Failed=1 of 330: CreditsRun.Job.Tests.ps1:176 'AC-B.7: Stop-CreditsJob ends every member (empty), and after the last handle closes the proof is gone' — Expected 'gone', But was 'unknown'. Passed in run 1; the file is outside this change",
  "receipt_sha256": "24bec76005bb81b0328ac8338c3a543478688bb2af06020d22e648e1b352409a",
  "fresh": true,
  "snapshot": false
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "h1-2-pester-flake-isolation",
  "cwd": "P:/agentic-framework",
  "scope": "CreditsRun.Job.Tests.ps1 alone, three runs",
  "phase": "runtime",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "84ae0d929ed1a7c54f5f9fc0fe6c6262e7f9f233041d2ffdff4b5dd4f9d7c154 (H1-2 run 2, before the round-1 F-001 fix; the identity lists paths, not contents)",
  "command": "pwsh -NoProfile -Command \"$c=New-PesterConfiguration; $c.Run.Path='C:/temp/agentic-framework/rl-stage/tools/tests/CreditsRun.Job.Tests.ps1'; $c.Run.PassThru=$true; Invoke-Pester -Configuration $c\" (x3)",
  "output": "after H1-2 run 2: run 1 passed=16 failed=0; run 2 passed=16 failed=0; run 3 passed=16 failed=0"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "h1-2-pester-noenv-invalid",
  "cwd": "P:/agentic-framework",
  "scope": "every staged Pester suite",
  "phase": "full",
  "result": "fail",
  "exit_code": 1,
  "tested_state": "84ae0d929ed1a7c54f5f9fc0fe6c6262e7f9f233041d2ffdff4b5dd4f9d7c154 (H1-2 run 2, before the round-1 F-001 fix; the identity lists paths, not contents)",
  "command": "pwsh -NoProfile -File docs/execution/plans/2026-10-20-review-limits-parameters/run_pester.ps1 C:/Temp/agentic-framework/rl-stage/tools/tests (launched without RECEIPTS_DIR / AGENT_MODEL_REGISTRY_HOME)",
  "output": "Failed=52 of 330, each one 'the mock started' / mock CLI calls file missing: an operator error (the two env vars that h1-2.ps1 sets were not set), not a code result; the run is discarded and the gate re-run with the env",
  "receipt_sha256": "a2ed72940fa41d3e05ea155c04dd0b4fbff3e09ff5135b2655306db00794f7d3",
  "fresh": true,
  "snapshot": false
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "h1-2-pester",
  "cwd": "P:/agentic-framework",
  "scope": "every staged Pester suite (baseline 324 passed)",
  "phase": "full",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "d1091f81158afe2bbadec72ce9c11dda616dbd123a0ebe18feb877753594b474",
  "command": "$env:RECEIPTS_DIR='C:/Temp/agentic-framework/receipts'; $env:AGENT_MODEL_REGISTRY_HOME='P:/.agent'; pwsh -NoProfile -File docs/execution/plans/2026-10-20-review-limits-parameters/run_pester.ps1 C:/Temp/agentic-framework/rl-stage/tools/tests",
  "output": "Pester gate PASS: Result=Passed Passed=330 Failed=0 FailedBlocks=0 FailedContainers=0 Skipped=0 Uncovered=0 (H1-2 run 3, after the F-001 fix)",
  "receipt_sha256": "1ec7bd58dc4695354f1a7ce9e560cc26e94b58f360cc3af394502500d5d10a18",
  "fresh": true,
  "snapshot": false
}
```

### Quality Gate Results

```
pyflakes (4 changed modules): 0 findings
pytest core/tools/tests + scripts/tests: 2235 passed, 50 warnings, 36 subtests passed in 2030.31s (0:33:50)
staged credits pytest: 513 passed, 50 skipped, 1560 deselected, 50 warnings in 772.70s (0:12:52)
staged Pester: Pester gate PASS: Result=Passed Passed=330 Failed=0 FailedBlocks=0 FailedContainers=0 Skipped=0 Uncovered=0
review_ledger.py selftest: RESULT: 125 arm(s), 0 failure(s) [62 must-OK arms, so the tool is not refusing everything]
instantiate.py --selftest: RESULT: 44 arm(s), 0 failure(s) [44 passing this run; a validator that always raises cannot pass]
refcheck: UNRESOLVED 0
anti-placeholder: stage verify OK (0 placeholder tokens remain)
```

No pyright or ruff gate: this package's §1 static gate is pyflakes (task row H1-2).

---

## Changed Files

22 tracked files modified (1242 insertions, 104 deletions), plus 6 new files.

| File | Action | Summary |
|------|--------|---------|
| `core/.agent/review-limits.json` | new | The shipped defaults (AC-1). |
| `core/tools/review_ledger.py` | modified (+486) | `load_repo_limits`, `load_plan_limits`, resolution in `cmd_begin`, `--round-budget`, `--token-budget N\|off`, `limits_source`, "off" handling, strict 0/null refusal, 20 selftest arms; `verified_limits` binds a loosened block to the block `limits-check` printed (round-1 F-001). |
| `core/tools/run_parameters.py` | modified (+188) | `limits-check` verb, `run-parameters-offer/2` parsing, `audit_round_cap`. |
| `core/.agent/run-parameters/schemas/run-parameters-offer.v2.schema.json` | new | The /2 offer schema with `review_limits` (AC-14). |
| `scripts/instantiate.py` | modified (+196) | `--round-caps`, `--token-budgets`, config keys, plan line, `--verify`, 12 selftest arms; `test_review_limits_audit.py` joins `RUN_PARAMETERS_WINDOWS_ONLY` (it builds the activated run-parameters fixture, which a non-Windows install removes). |
| `core/tools/credits_state.py` | modified (+141) | Optional caps, `repo_token_budgets`, `omitted_caps`, `caps_reason`, uncapped admission, `None` chain room. |
| `core/.agent/skills/claude-credits/schemas/credits-run.v1.json` | modified | The three caps leave `required`; their properties stay. |
| `core/.agent/skills/claude-credits/Start-CreditsRun.ps1` | modified | `-MaxBudgetUsd 0.0` and `uncapped` in the admitted log line. |
| `core/.agent/skills/claude-credits/SKILL.md` | modified | §Schedule: optional caps under `token_budgets: "off"` and what bounds an uncapped run. |
| `core/.agent/workflows/create-plan.md`, `execution-session.md`, `delegated-plan-creation.md`, `validation-review.md`, `core/.agent/skills/cli-dispatch/SKILL.md`, `core/.agent/docs/development-lifecycle.md` | modified | Fixed-cap prose names its source (AC-17); `begin` examples gain `--goal-anchor`/`--ac-file`. |
| `core/templates/PLAN-TEMPLATE.md`, `core/templates/TASK-TEMPLATE.md` | modified | The `review_limits` block; versions 2.4 / 2.5 (AC-18). |
| `ADOPTION-QUESTIONS.md`, `PROJECT-PROFILE-TEMPLATE.md` | modified | B5 and B5b (AC-19). |
| `core/MANIFEST.md` | modified | New §5f and the ledger's resolution order (AC-20). |
| `scripts/refcheck.py` | modified (+9) | **Outside Files Modified (D-14):** three pinned `NOT_A_PROMISE` entries. |
| Tests | new / modified | New: `test_review_limits.py` (58), `test_review_limits_audit.py` (46), `test_credits_uncapped.py` (37), `scripts/tests/test_instantiate_review_limits.py` (22). Modified: `Start-CreditsRun.Tests.ps1`, `Register-CreditsRun.Tests.ps1`, `scripts/tests/test_run_parameters_template.py` (version pins). |

Key hunks:

```diff
 # core/tools/credits_state.py, verb_admit
-                rooms = [manifest.segment_cap_usd, manifest.run_cap_usd - spent]
+                reason = caps_reason(doc)
+                if reason is None:
+                    rooms = [...only the caps that are present...]
+                    uncapped = not rooms
+                    reservation = 0.0 if uncapped else money(min(rooms))
```

```diff
 # core/.agent/skills/claude-credits/schemas/credits-run.v1.json
-      "required": ["working_directory", ..., "effort", "segment_cap_usd", "timeout_sec"],
+      "required": ["working_directory", ..., "effort", "timeout_sec"],
```

```diff
 # scripts/refcheck.py, NOT_A_PROMISE (D-14)
+    (".agent/context/handoffs/2026-10-20-review-limits-parameters-plan-critical-review.md", 196, "core/tools/run_parameters.py.orig"): (...),
+    ("docs/execution/plans/2026-10-20-review-limits-parameters/implementation-plan.md", 232, "core/.agent/workflows/execution-session.md:182–205"): (...),
+    ("docs/execution/plans/2026-10-20-review-limits-parameters/task.md", 41, "scripts/tests/test_instantiate_review_limits.py::test_shipped_file_equals_constants"): (...),
```

---

## Codex Validation Report

_Left blank for the reviewer agent._

### Points raised for the reviewer

1. **D-14, scope:** `scripts/refcheck.py` gained three pinned exemptions so that row 5 (AC-20)
   passes without editing the approved plan or the plan-review record. Accept, or rule another way out.
2. **Open design point (not pinned):** `run-parameters-offer.v2.schema.json` decides which
   offers can loosen limits and `review_ledger.py` enforces them, yet neither is in
   `REQUIRED_COMPONENTS`. Pinning was outside the plan's scope (D-17).
3. **H1-1 predicate gap:** the unchecked-row check skips ids such as `5c2`. Every row was also
   checked by an explicit grep.
4. **Follow-up:** `validation-review.md`'s `begin` example still lacks `--goal-anchor` / `--ac-file`.

---

## Corrections Applied (2026-10-21)

Execution review round 1 (`changes_required`, 1 finding). The review is
`.agent/context/handoffs/2026-10-20-review-limits-parameters-implementation-critical-review.md`.

**Findings resolved**: 1/1

| # | Finding | Fix Applied | Verification |
|---|---------|-------------|--------------|
| F-001 | `begin` could install a loosened block from a different file than `limits-check` verified: the check got only the `--ac-file` folder's slug and read the repository plan, while `resolve_limits` installed the caller's block. A same-slug `--ac-file` outside the repository opened 999 rounds with tokens off. | `resolve_limits` now reads the `review_limits` that the passing `limits-check` printed (`verified_limits`) and refuses unless it equals the block it is about to install, key for key. A pass with no printed block, or a different one, is refused. | Red then green: `test_begin_refuses_a_same_slug_ac_file_with_other_limits` runs the real `limits-check` (records `f001-red` and `f001-green`). `test_loosened_block_needs_limits_check` now shows that a stub pass without the verified block is refused. Selftest arm `limits-loosened-other-block-refused`. H1-2 run 3 passed in full. |

---

## Deferred Items

None. Points 3 and 4 above are observations about shipped tooling outside this plan's scope,
not unfinished work of this plan.

---

## Decision Log

```yaml
decision_log:
  - id: D-14
    stage: execution
    question: "Row 5's refcheck finds 3 unresolved references, all in this plan's approved records or review history; how to pass AC-20?"
    resolution: autonomous
    class: two-way
    chosen: "Three NOT_A_PROMISE entries in scripts/refcheck.py, each pinned to file:line -> ref with its reason; the plan and the review record stay unedited."
    source_tag: Local Canon
    precedents: ["scripts/refcheck.py NOT_A_PROMISE — keyed historical-record exemptions, e.g. the 2026-09-19 adopter findings"]
    research: { engine: none, sources: ["none: internal tooling question"] }
    reasoning: "Editing an approved plan or a review record rewrites history; an unpinned exemption could widen. A pinned entry fails again if the line moves. refcheck.py is outside Files Modified, so the reviewer rules on it."
  - id: D-15
    stage: execution
    question: "Row 5c's verbatim python -c fails under pwsh with a quoting error; how to run its check?"
    resolution: autonomous
    class: two-way
    chosen: "Run the same four checks from a script file and record the deviation; a negative run against d698342 exits 1."
    source_tag: Local Canon
    precedents: ["task.md row 5c — the four checks named in the row"]
    research: { engine: none, sources: ["none: shell quoting"] }
    reasoning: "pwsh passes the escaped quotes through to Python unchanged; the checks themselves are what the row requires, and the negative run proves the script can fail."
  - id: D-16
    stage: execution
    question: "The approved prose says an uncapped run stopped by caps_required resumes once it is given caps, but a started run cannot be registered again; which wins?"
    resolution: autonomous
    class: source-conflict
    chosen: "The code: SKILL.md and ADOPTION-QUESTIONS say a stopped run cannot resume; register a new run with caps, or set the switch back to off."
    source_tag: Local Canon
    precedents: ["core/tools/credits_state.py verb_register — already_started / manifest_changed refusals"]
    research: { engine: none, sources: ["none: internal behaviour"] }
    reasoning: "The docs must describe what the store does; changing re-registration was out of scope."
  - id: D-17
    stage: execution
    question: "Should the /2 offer schema and review_ledger.py join REQUIRED_COMPONENTS?"
    resolution: autonomous
    class: two-way
    chosen: "No, as planned; raised to the execution reviewer as an open design point."
    source_tag: Local Canon
    precedents: ["implementation-plan.md §Files Modified — no REQUIRED_COMPONENTS change"]
    research: { engine: none, sources: ["none: scope question"] }
    reasoning: "Pinning changes the activation policy of every adopter and was not in the approved scope; the reviewer can require it."
  - id: D-18
    stage: execution
    question: "How should begin bind a loosened block to the block limits-check verified (round-1 F-001)?"
    resolution: autonomous
    class: two-way
    chosen: "Compare the review_limits that the passing limits-check printed with the block begin installs, key for key; refuse on any difference, or when none was printed."
    source_tag: Local Canon
    precedents: ["core/tools/run_parameters.py _cmd_limits_check — prints review_limits on limits_verified", "F-001 recommendation: compare structured verified limits against the caller's block"]
    research: { engine: none, sources: ["none: internal binding"] }
    reasoning: "A path-equality check would depend on how the ledger's REPO_ROOT and the verb's git top-level line up, which differs between the template tree and an installed repo. Comparing the values binds what is installed to what was verified wherever the file lives. The round-2 review approved it."
```

---

## History

| Event | Date | Agent | Detail |
|-------|------|-------|--------|
| Created | 2026-10-20 | implementing agent | Implementation rows 0–7c done |
| H1-2 run 1 | 2026-10-21 | implementing agent | Two failures, both fixed: (1) `test_retained_python_tests_collect` (in `scripts/tests/test_instantiate_credits_nonwin.py`) — the non-Windows install kept `test_review_limits_audit.py` but removed `run_parameters_fixtures`, so collection failed; the test now goes with the other fixture users in `RUN_PARAMETERS_WINDOWS_ONLY`. (2) refcheck read this handoff's file-colon-test cells as paths; the cells now name the file and the tests separately. |
| H1-2 run 2 | 2026-10-21 | implementing agent | Full verification fresh at state `84ae0d92…`. One Pester flake, re-run green. Superseded by run 3 after F-001; the run-2 failure records stay in Evidence with their state |
| Submitted for review | 2026-10-21 | implementing agent | To Codex, ledger loop `exec-2026-10-20-review-limits-parameters`, round 1 |
| Execution review round 1 | 2026-10-21 | codex | `changes_required`: F-001 (High, control-defeat, AC-13) |
| Corrections applied | 2026-10-21 | implementing agent | 1 finding resolved (F-001). H1-2 run 3 passed fresh at the new state; the run-2 records keep their state and are labelled as such |
| Resubmitted for review | 2026-10-21 | implementing agent | Round 2 |
