---
date: "2026-10-21"
review_mode: "execution"
target_plan: "docs/execution/plans/2026-10-20-review-limits-parameters/implementation-plan.md"
verdict: "approved"
findings_count: 0
template_version: "2.2"
requested_verbosity: "standard"
agent: "gpt-6.1-sol"
---

# Critical Review: 2026-10-20-review-limits-parameters

> **Review Mode**: `execution`
> **Verdict**: `approved`

## Scope

**Target**: The project handoff, approved implementation-plan/task, all 22 tracked-file diffs, six new implementation/test files, plan-review history, and execution evidence log supplied in the dispatch. HEAD: `e667fb6`; implementation remains uncommitted.

**Review Type**: Execution critical review, findings only.

**Checklist Applied**: Runtime/contract, negative paths, test rigor, AC coverage, documentation and evidence consistency (IR/DR/PR).

## Findings

**Current status (Round 2): zero open findings; F-001 fixed.** The Round 1 report below is retained as written; its open row describes the prior state.

| # | Severity | Blocking | Kind | Finding | File:Line | Recommendation | Status |
|---|----------|----------|------|---------|-----------|----------------|--------|
| F-001 | High | no | control-defeat | **Closed on recheck:** the block used by `begin` must equal the block printed by a passing verifier. Subject: deliverable; confidence: High; mechanism: `verdict-to-state-transition`; AC-13. | `core/tools/review_ledger.py:429`; `core/tools/review_ledger.py:485`; `core/tools/tests/test_review_limits_audit.py:329` | None; retain the regression test. | fixed |

## Round 1 (2026-10-21)

**Intent anchor**: "Make review round caps and token budgets setup choices in the repo, adopted by each plan and execution as tighten-only defaults, with loosening only through a verified human-typed offer."

**Intent achieved**: `partial`. Setup choices, ordinary resolution, legacy behavior and uncapped credits behavior work in the reviewed cases. The resolver can apply loosened values from a different file than the one the human offer verified.

## Findings

| # | Severity | Blocking | Kind | Finding | File:Line | Recommendation | Status |
|---|----------|----------|------|---------|-----------|----------------|--------|
| F-001 | High | yes | control-defeat | **A same-slug alternate AC file inherits authorization for different limits.** `run_limits_check(plan)` passes only `plan.parent.name` to the verifier. That verifier checks the canonical plan in the repository, while `resolve_limits` subsequently installs the block read from the caller's arbitrary `--ac-file`. A real self-contained /2 offer for execution rounds **9**, tokens **21000000** passes; an alternate `.../alternate/<same-slug>/implementation-plan.md` requesting rounds **999**, tokens **off** then opens successfully with those unoffered values. No authority code, policy or transcript was altered. Violates **AC-13**, specifically offered-block equality. Subject: deliverable; confidence: High; mechanism: `verdict-to-state-transition` (verification of one artifact admits state from another). | `core/tools/review_ledger.py:420`; `core/tools/review_ledger.py:464`; `core/tools/review_ledger.py:472`; counterpart `core/tools/run_parameters.py:5884` | Bind authorization to the exact block being installed. For example, require a loosened AC file to resolve to the canonical verified plan, or compare the verifier's structured, verified block with the caller's parsed block before saving. Add the real-verifier same-slug alternate-file negative case; keep the canonical positive case. | open |

### F-001 reproduction and test gap

The independent probe uses the existing activated fixture builder, real human transcript fixture, and real `limits-check` child process. It changes only the fixture repository and files under the reviewer receipt directory. The alternate carrier has the six valid keys and a truthful `basis: loosened`. There is no sibling task in that alternate directory; AC-8 explicitly permits its absence.

1. Build the standard fixture; use `test_review_limits_audit._self_contained(fx)` to authorize the canonical `LOOSENED` block (9 execution rounds, 21000000 execution tokens).
2. Observe `fx.run('limits-check', '--plan', fx.plan)` return `limits_verified` with those exact values.
3. Write another `implementation-plan.md` below a different parent tree with the **same plan-folder slug**, changing execution rounds to 999 and execution tokens to off.
4. Call the real ledger `begin` with `--ac-file` pointing to that alternate file and `REPO_ROOT` pointing to the activated fixture repository.
5. Observe exit 0 and persisted `round_budget=999`, `token_budget="off"`.

The integration tests `test_begin_opens_a_loosened_loop_after_limits_check` always pass `fx.plan_path()`. Their refusal cases likewise mutate canonical carriers. They correctly exercise those cases, but can all pass while the check/use identity mismatch remains. The unit seam that returns `(0, "OK")` for `run_limits_check` also cannot detect it.

```json
{
  "schema_version": "evidence.v1",
  "check_id": "r1-offer-block-identity",
  "command": "rtk proxy python -B C:/Temp/agentic-framework/receipts/dispatch/review-limits-exec-r1/reviewer_checks.py probes",
  "cwd": "P:/agentic-framework",
  "scope": "AC-13: real limits-check versus the block begin installs",
  "phase": "targeted",
  "exit_code": 1,
  "result": "fail",
  "tested_state": "HEAD e667fb6 plus supplied working-tree implementation",
  "output": "CANONICAL_LIMITS_CHECK (0, result=limits_verified, execution_rounds=9, execution_tokens=21000000); alternate AC file: OK opened loop unoffered-clone mode=execution budget=999 tokens=off; ALTERNATE_AC_FILE_BEGIN_EXIT 0; ACTUAL_LIMITS 999 off. AssertionError: AC-13 FAIL: begin accepted unoffered alternate-file limits. Negative probe exits 1."
}
```

## Checklist Results

### Information Retrieval / implementation contracts (IR)

Each AC was checked against implementation and assertions, not inferred from a green suite alone.

| AC | Result | Code and test assessment |
|----|--------|--------------------------|
| AC-1 | pass | Shipped JSON matches ledger round/token constants, with switch on; tests compare exact maps and key order, and invoke the actual reader. |
| AC-2 | pass | Installer parses/validates answers before writes; flags replace config values; other mode values survive. CLI tests compare actual bytes/values and unchanged tree snapshots after malformed flags/config. |
| AC-3 | pass | No answer produces no limits rewrite; test compares shipped bytes after a real installation. |
| AC-4 | pass | Verify uses the installed ledger reader, disables import bytecode writes, and refuses invalid limits; tests check snapshot identity after refusal. |
| AC-5 | pass | `resolve_limits` reads repo bytes, resolves mode values/switch and records the content digest. Non-default repo values are asserted in the saved ledger. |
| AC-6 | pass | Absent repo file selects constants; malformed JSON, shape and zero values fail closed without creating a ledger. The reader also rejects duplicate JSON keys, booleans and missing modes. |
| AC-7 | pass | Strict six-key scalar parser, computed basis relation, plan/execution-only application and recorded plan source match the ordinary-path contract. Malformed/zero blocks and basis mismatches return 3. F-001 concerns the separate loosening verification contract. |
| AC-8 | pass | Present sibling task block must equal the AC-file block; mismatch refuses, missing task/block is allowed. Tests exercise each result. |
| AC-9 | pass | Flags apply after repo/plan resolution and compare against the resolved limit. Off is looser than every number. Looser flags refuse; zero/invalid values are argparse errors. |
| AC-10 | pass | Off avoids token-budget arithmetic and token stops, retains usage reporting and rejects continue --tokens; saved 0/null/invalid budgets fail closed. Numeric budget 1 still stops. |
| AC-11 | pass | Existing stop logic remains in place; selftest independently reports 124 arms, zero failures, 62 must-OK. Off-loop round-cap behavior is also directly asserted. |
| AC-12 | pass | Legacy ledger fixture has no limits_source; exact stops, state and continuation outcomes pass. No repo file still resolves constants. |
| AC-13 | **fail** | Canonical positive/refusal cases pass, including human provenance, reply/manual/legacy/disabled/off-Windows rejection. The independent alternate-file probe defeats offered-block equality: F-001. |
| AC-14 | pass | /1 remains exact-key and excludes review_limits; /2 requires it and validates six typed keys. Quoted round counts are refused. JSON Schema and parser cases are exercised. |
| AC-15 | pass | `audit_round_cap` uses ledger base plus grants, refuses wrong mode/malformed state and a task block without a ledger, then uses repo/constants only for legacy fallback. Tests invoke stage validators and inspect actual cap/refusal outcomes. |
| AC-16 | pass | Limits-check uses read-only verification/store snapshots and no store creation. Tests compare full fixture file digests for success/refusal and absent-store paths. |
| AC-17 | pass | Step 0 explains repo/default/block/basis and verified loosening; operative inventory replacements identify their source in context. Independent inventory oracle passes current files and finds 27 problems at d698342. |
| AC-18 | pass | Optional blocks and source/basis notes are in both templates; versions 2.4/2.5. Configured-cap wording points at live ledger state. Template tests (20) and linter/closeout selftests (50/174 arms) pass. D-15 accepted below. |
| AC-19 | pass | Both setup documents name B5/B5b, flags, USD behavior, retained timeout and the next-admission effect of returning to on. Source reads supplement the narrower grep predicate. |
| AC-20 | pass | MANIFEST lists config/resolution order; execution workflow explains sources and off handling. Refcheck independently reports zero unresolved/unclassified references; D-14 accepted below. |
| AC-21 | pass | Optional-cap registration, present-cap validation, minimum room/floor, switch-back admission refusals, exposure and chain behavior checked in source and 37 subprocess tests. Launcher preserves capped reservation and passes explicit zero only for an uncapped admission; actual mock-CLI argv is checked by Pester. Two changed Pester suites pass 64/64 in the reviewer stage with unused TestRegistry disabled. Matching prior full-stage evidence remains separately identified below. |

**Test rigor**: All tests in the four new Python files and the new/changed Pester groups were inspected. Behavioral cases are **Strong**: exact saved limits, refusal codes, unchanged-file snapshots, store state/notices, spend/chain results and real mock-CLI argv. Static inventory/version/text assertions are **Adequate** for their documentary contracts. No vacuous assertion was identified. F-001 identifies a missing materially different negative case, rather than a separate duplicate test finding. The template test modifications only update version expectations; their behavioral regression suite also passed independently.

**Non-Windows disposition**: Adding `test_review_limits_audit.py` to `RUN_PARAMETERS_WINDOWS_ONLY` is correct: it imports/builds the activated run-parameters fixtures that are intentionally removed there. `test_review_limits.py` depends on retained ledger code. `test_credits_uncapped.py` imports retained `test_credits_state.py` and uses retained credits_state/review_ledger code. The installer test lives outside the adopted core. Independent simulated non-Windows install, dependency scans and collection all pass (4 tests). No second newly exposed removed dependency was found.

### Design and documentation rulings (DR)

| Point raised | Ruling |
|--------------|--------|
| D-14: three pinned NOT_A_PROMISE entries outside Files Modified | **Accept.** Each exemption is an exact file/line/reference tuple with a verifiable reason: historical backup observation, en-dash line citation, or pytest node ID. The latter two underlying files/nodes exist. This is a bounded validation adjustment, with zero stale exemptions, rather than a blanket suppression of delivered dangling paths. |
| D-15: row 5c equivalent script | **Accept.** The check still asserts both blocks and both exact version strings; the negative historical run is recorded. Independent template checks and selftests confirm the delivered state. Shell quoting failure was disclosed. |
| D-16: resume wording follows code | **Accept.** Existing `verb_register` rejects an already-started run and changed manifests. AC-21 requires next-admission refusal, not an in-place recap/re-registration feature. New capped run or restoring off accurately describes available recovery. |
| D-17: /2 schema and review_ledger.py absent from REQUIRED_COMPONENTS | **Accept this scope disposition, with residual code-drift risk.** Runtime /2 offer validation is implemented in the pinned run_parameters.py parser; the schema file itself does not grant authority. The ledger helper remains unpinned. Expanding activation-policy coverage is a separate integrity change not required by an AC here; arbitrary authority-code replacement is not the F-001 reproduction. Do not characterize this as proof that all authority dependencies are pinned. |
| H1-1 predicate misses 5c2 | **Non-blocking.** The predicate is incomplete, but independent explicit enumeration confirms every implementation row 0–7c (including 5c2) and H1-1–H1-6b is checked, with corresponding deliverables/evidence. No missing product work was hidden. Generalize the row parser in follow-up. |
| validation-review.md begin example | **Non-blocking pre-existing follow-up.** It still omits required --goal-anchor/--ac-file and would exit 2. This change updates its limits-source prose, and does not introduce the missing flags. Correct the example in workflow upkeep; it does not negate a delivered AC. |
| H1-2 Pester gone/unknown flake | **Disposition sound for this change.** The failure was retained rather than waived, and the entire gate was rerun to an outright 330-pass result on the recorded same state. The test/module are untouched; `Get-CreditsJobProof` deliberately returns unknown when process death/open state cannot be proved immediately. That makes transient observation timing plausible, but the exact cause is unproven. Keep it classified intermittent, not fixed. No renewed full 15-minute run was justified by this implementation review. |

IR API/stub/error-mapping checks are not applicable to this CLI/framework change. Build-plan/MEU/OpenAPI no-op bases match the package. H2 work is correctly pending behind this review; it is not an implementation omission.

### Post-implementation evidence review (PR)

The independent configured D6 identity is `84ae0d929ed1a7c54f5f9fc0fe6c6262e7f9f233041d2ffdff4b5dd4f9d7c154`, equal to the handoff. As declared by the plan, this hashes HEAD, porcelain status and Python version; it is **not a historical content hash**. I also saved an independent content snapshot of current tracked/untracked non-ignored files and compared it after review: zero changes. No repository file was edited and no repository commit was created.

Matching full-run receipt bytes were independently hashed and their decisive output read:

| Prior full check | Verified receipt SHA-256 | Decisive result |
|------------------|------------------------|-----------------|
| Full pytest | `cb1ab6125b92e85d94075bb6d01a96088551d5e2943f460c6b9f4c5cc8c79c1c` | 2234 passed, 50 warnings, 36 subtests passed |
| Staged credits pytest | `1898c1037fa53597c1449a8fe16cddb85b6b9c569a2c9bbc94bb0e3588ec9b1b` | 513 passed, 50 skipped, 1559 deselected |
| Entire staged Pester gate | `64aa8208f4d5af537aa3d8b121f1f5ef0d37e8a857f14043b97a651401ec8636` | Passed=330, Failed=0, FailedBlocks=0, FailedContainers=0, Skipped=0, Uncovered=0 |

The full suites were **not freshly rerun by this reviewer**. The matching prior evidence was retained as instructed; independent targeted checks exposed F-001. Corrections to that resolver will require affected checks and a fresh full gate under the workflow.

The first four-file targeted reviewer run gave **125 passed / 37 fixture errors**: fixture git commits tried the user's inaccessible signing key. With process-local `commit.gpgsign=false` for fixture commits, all 37 credits tests passed. No signing policy/config was edited. An initial shell launch with misquoted environment assignments was interrupted and contributes no passing evidence; subsequent runs explicitly set `PYTHONDONTWRITEBYTECODE=1` and use `-B`/`-p no:cacheprovider`.

The template regression initially failed because nested pytest used an inaccessible default temporary location; setting TEMP/TMP below receipts produced 20 passes. The exact Pester gate initially stopped at its passing self-check because Pester TestRegistry cannot create `HKCU/Software/Pester` in this dispatch sandbox. A standalone passing-test host probe reproduced the registry SecurityException. The supplemental targeted run disabled **only the unused TestRegistry plugin** and retained assertions/count/failure/container checks. It is not represented as a fresh pass of the unmodified full gate.

```json
{
  "schema_version": "evidence.v1",
  "check_id": "r1-targeted-ordinary-paths",
  "command": "python -m pytest core/tools/tests/test_review_limits.py core/tools/tests/test_review_limits_audit.py core/tools/tests/test_credits_uncapped.py scripts/tests/test_instantiate_review_limits.py -q -rfE -p no:cacheprovider --basetemp=C:/Temp/agentic-framework/receipts/dispatch/review-limits-exec-r1/pytest-temp-2",
  "cwd": "P:/agentic-framework",
  "scope": "AC-1..AC-16 and AC-21(a)-(e); PYTHONDONTWRITEBYTECODE=1, RECEIPTS_DIR and registry home set",
  "phase": "targeted",
  "exit_code": 1,
  "result": "blocked",
  "tested_state": "HEAD e667fb6 plus supplied working-tree implementation",
  "output": "125 passed, 37 errors in 55.30s. All 37 errors are fixture setup git commits; independent direct reproduction: No private key found for C:/Users/Mat/.ssh/id_ed25519_signing; fatal: failed to write commit object. The other three targeted files passed."
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "r1-credits-and-nonwin",
  "command": "rtk proxy python -B C:/Temp/agentic-framework/receipts/dispatch/review-limits-exec-r1/reviewer_checks.py rerun",
  "cwd": "P:/agentic-framework",
  "scope": "credits cap runtime and simulated non-Windows installer; process-local fixture signing disabled",
  "phase": "targeted",
  "exit_code": 0,
  "result": "pass",
  "tested_state": "HEAD e667fb6 plus supplied working-tree implementation",
  "output": "pytest core/tools/tests/test_credits_uncapped.py: exit 0, 37 passed in 32.85s. pytest scripts/tests/test_instantiate_credits_nonwin.py: exit 0, 4 passed in 3.06s. Both use -p no:cacheprovider, explicit receipt basetemp, PYTHONDONTWRITEBYTECODE=1."
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "r1-template-regression",
  "command": "rtk proxy python -B C:/Temp/agentic-framework/receipts/dispatch/review-limits-exec-r1/reviewer_checks.py template_short",
  "cwd": "P:/agentic-framework",
  "scope": "template version and instantiated-adopter regressions; TEMP/TMP below receipts",
  "phase": "targeted",
  "exit_code": 0,
  "result": "pass",
  "tested_state": "HEAD e667fb6 plus supplied working-tree implementation",
  "output": "pytest scripts/tests/test_run_parameters_template.py -q -rfE -p no:cacheprovider: 20 passed in 28.87s, child exit 0."
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "r1-launcher-registration-runtime",
  "command": "rtk proxy python -B C:/Temp/agentic-framework/receipts/dispatch/review-limits-exec-r1/reviewer_checks.py pester_supplement",
  "cwd": "P:/agentic-framework",
  "scope": "new reviewer-instantiated stage; Start-CreditsRun.Tests.ps1 and Register-CreditsRun.Tests.ps1; TestRegistry.Enabled=false due sandbox registry denial",
  "phase": "runtime",
  "exit_code": 0,
  "result": "pass",
  "tested_state": "HEAD e667fb6 plus supplied working-tree implementation, instantiated in reviewer receipts",
  "output": "Discovery found 64 tests in 2 files. Tests Passed: 64, Failed: 0, Skipped: 0, Inconclusive: 0, NotRun: 0. REVIEWER_TARGETED: Result=Passed Passed=64 Failed=0 FailedBlocks=0 FailedContainers=0 Containers=2. Child exit 0."
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "r1-static-selftests-and-coverage",
  "command": "rtk proxy python -B C:/Temp/agentic-framework/receipts/dispatch/review-limits-exec-r1/reviewer_checks.py quick; rtk proxy python -B C:/Temp/agentic-framework/receipts/dispatch/review-limits-exec-r1/reviewer_checks.py final_checks",
  "cwd": "P:/agentic-framework",
  "scope": "individual independently captured child results listed in output; not a blanket pass of every quick-driver child",
  "phase": "targeted",
  "exit_code": 0,
  "result": "pass",
  "tested_state": "HEAD e667fb6 plus supplied working-tree implementation",
  "output": "Each listed child exited 0: pyflakes four changed modules (no findings); ledger selftest 124 arms/0 failures; instantiate selftest 44/0; task lint selftest 50/0; closeout selftest 174/0; AC-17 oracle 0 current problems/27 historical; refcheck UNRESOLVED 0, UNCLASSIFIED 0, stale exemptions 0; run-parameters policy all checks passed; AC coverage all 21 present. Explicit 25-row implementation/H1 enumeration all checked, including 5c2. Content snapshot comparison: REVIEWED_FILE_CONTENT_CHANGES []. The earlier template child failure in quick is disclosed separately and superseded only by its own successful rerun."
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "r1-prior-full-binding",
  "command": "rtk proxy python -B C:/Temp/agentic-framework/receipts/dispatch/review-limits-exec-r1/reviewer_checks.py identity",
  "cwd": "P:/agentic-framework",
  "scope": "independent configured D6 identity, handoff full evidence validation, and full-receipt byte hashes",
  "phase": "targeted",
  "exit_code": 0,
  "result": "pass",
  "tested_state": "84ae0d929ed1a7c54f5f9fc0fe6c6262e7f9f233041d2ffdff4b5dd4f9d7c154",
  "output": "D6_STATE equals the recorded state. Passing full pytest, staged credits pytest and full staged Pester receipt SHA-256 values each match the handoff. durable_evidence.py --require-full --expected-state <independently computed state>: child exit 0, OK: durable evidence records. Historical failed runs remain failed and were not used as passing evidence."
}
```

## Verdict

`approved` — Round 2 closes F-001. No open findings remain. The verified limits are the limits installed, AC-5..AC-13 regression checks pass, and the regenerated full evidence matches the independently obtained current D6 state. The complete recheck is below. No repository files were edited and no commit was created.

## Recheck (2026-10-21)

### Round 2 (2026-10-21)

**Workflow**: `/execution-critical-review`, execution loop `exec-2026-10-20-review-limits-parameters`, round 2 of 6.

**Agent**: `gpt-6.1-sol`, as recorded in the dispatch command; independent of the Claude implementer.

**Intent anchor**: "Make review round caps and token budgets setup choices in the repo, adopted by each plan and execution as tighten-only defaults, with loosening only through a verified human-typed offer."

**Intent achieved**: `yes`.

### Prior Pass Summary

| Finding | Prior Status | Recheck Result |
|---------|--------------|----------------|
| F-001 — verified block versus installed block (High, AC-13, `verdict-to-state-transition`) | open | **Fixed.** Same-slug alternate-file requests for unoffered limits now exit 1 and leave no ledger. |

### Confirmed Fixes

`verified_limits` extracts the first JSON object whose result is `limits_verified` (`core/tools/review_ledger.py:429`). After a successful child exit, `resolve_limits` compares that entire dictionary to the already parsed block and refuses inequality before any ledger save (`:485`). The round/token values subsequently installed come from that same in-memory block (`:492`), so changing a file after verification cannot substitute different values.

The newly added integration regression (`core/tools/tests/test_review_limits_audit.py:329`) invokes the real verifier, establishes a passing canonical offer, changes only the alternate carrier, and asserts exit 1, the specific refusal and absence of a ledger. Its assertion strength is **Strong**. The changed unit test (`core/tools/tests/test_review_limits.py:309`) now rejects an exit-0 stub with no verified block and preserves the exact-block positive case; **Strong** for its seam. The selftest's added refusal arm (`core/tools/review_ledger.py:2148`) also covers a different printed block. No existing AC assertion was weakened.

The Round 1 content snapshot and retained stage copies identify the complete correction delta: the ledger, these two Python tests, the work handoff, and the newly copied Round 1 review. All other reviewed implementation, tests, plan/task and decision-bearing documents retain their Round 1 content hashes. The old stage copies of all three Python files match their recorded Round 1 hashes, allowing an exact source comparison rather than relying on the correction narrative.

### Independent Adversarial Checks

All **25** cases passed. Every negative case checked both its expected exit and the absence of a ledger; every positive case checked the persisted limits.

| Surface | Observed result |
|---------|-----------------|
| Same-slug alternate file, no task | 999 rounds / tokens off refused, exit 1, no ledger. |
| Alternate sibling task with matching unoffered values | Still refused by verified-block equality, exit 1, no ledger. |
| Alternate sibling task with different values | Refused by carrier equality, exit 1, no ledger. |
| Relative alternate `--ac-file`; relative canonical file | Alternate refused; canonical opened exactly 9 rounds / 21000000 tokens. Relative-path probes ran from the receipt fixture's directory because Windows cannot express a relative path between P: and C:. |
| Exact offered block in another file | Opened with exactly the offered values. AC-13 authorizes values; it does not require canonical-path identity. |
| Only `plan_rounds` differs during an execution begin | Refused, proving comparison covers the other mode's keys too. Alternate `task.md` used as `--ac-file` was likewise refused. |
| Canonical file edited after the real verifier returns | File then contains 999/off; saved ledger still contains verified 9/21000000. There is no second limits-file read to substitute the changed block. |
| Canonical unoffered block loaded, then restored before real verification | Verifier passes on offered block; begin refuses its different cached block, exit 1, no ledger. |
| Canonical block changed just before real verification | Real child refuses `binding` / `review_limits_differs`; begin exits 1 with no ledger. This probe edits only the carrier block, preserving the transcript/authorization. |
| Empty, truncated, partial, extra-key, unrelated-result or different-block verifier output | Refused, exit 1, no ledger. A valid JSON block accompanying child exit 1 is also refused. |
| Extra text, unrelated JSON and a partial JSON line surrounding the matching result | Matching verified block alone installed; no changed limits. |
| Multiple result lines | First partial/different result followed by a matching result refused. First matching result followed by a different one installed only the first matching block. See trust-boundary note below. |
| Positive plan mode and flag order | Plan mode opened 3/10500000; execution tightening flags opened 7/12000 after verified 9/21000000; flag 10 refused. |

File/path and mutation probes use the real activated fixture and real `limits-check` subprocess. Output-shape probes replace only `run_limits_check`'s returned exit/output tuple to exercise the new consumer boundary. No authority code, policy or human transcript was changed to obtain a bypass.

**Trust boundary / residual risk:** the parser consumes the first matching result rather than enforcing a one-record output protocol. The current producer emits one JSON result and serializes carrier data; no route from ordinary carrier input to a forged extra result was found. Arbitrary replacement of the trusted verifier output or authority code remains the already accepted Round 1/D-17 integrity boundary. No unoffered installed block was demonstrated. The tests model mutations at deterministic call boundaries; they do not claim exhaustive concurrent-filesystem assurance.

### Checklist Results

| Check | Result | Observation |
|-------|--------|-------------|
| F-001 / AC-13 / IR-4 | pass | Exact-block check closes the original reproduction and the independent variants above. |
| AC-5..AC-12 | pass | Repo/defaults, fail-closed parsing, modes, basis, sibling equality, flags, off, stops and legacy cases all pass in the affected suite. |
| AC-13..AC-16 | pass | Real-verifier acceptance/refusals, typed offer and audit/read-only cases pass in the affected suite. |
| Review output/ledger compatibility | pass | Output pipeline and v2 verdict-schema regressions pass alongside the affected tests: **113 passed** total. |
| IR-5 test rigor | pass | New and modified assertions audited as Strong; unchanged test files retain the Round 1 audit. |
| AC-1..AC-4, AC-17..AC-21; D-14..D-17 | pass | Implementation hashes unchanged since Round 1; prior rulings stand, with regenerated complete-gate evidence independently verified below. |
| Evidence freshness / DR-5 / DR-7 | pass | Independent D6 state, three full receipt hashes, gate run-3 summary and durable-evidence validation agree. |
| Review write scope | pass | Before/after content snapshots match; all reviewer artifacts and fixtures are outside the repository. |

The affected suite was freshly executed with bytecode disabled, the cache provider disabled, and a receipt-local pytest base directory. The initial independent probe driver stopped after four passing cases because `os.path.relpath` cannot cross drives; that is a reviewer fixture error, not product failure or passing evidence for the unexecuted cases. It was corrected by changing the probe cwd within receipts. A subsequent refinement preserved the authorization text during the before-check mutation so the real child reached the intended `review_limits_differs` refusal. The final driver passed all 25 cases.

```json
{
  "schema_version": "evidence.v1",
  "check_id": "r2-affected-regressions",
  "command": "$env:RECEIPTS_DIR='C:/Temp/agentic-framework/receipts'; $env:AGENT_MODEL_REGISTRY_HOME='P:/.agent'; $env:PYTHONDONTWRITEBYTECODE='1'; rtk proxy python -B -m pytest core/tools/tests/test_review_limits.py core/tools/tests/test_review_limits_audit.py core/tools/tests/test_review_output_pipeline.py core/tools/tests/test_review_verdict_schema_v2.py -q -rfE -p no:cacheprovider --basetemp=C:/Temp/agentic-framework/receipts/dispatch/review-limits-exec-r2/pytest-temp",
  "cwd": "P:/agentic-framework",
  "scope": "AC-5..AC-16 and review-output/schema compatibility",
  "phase": "targeted",
  "exit_code": 0,
  "result": "pass",
  "tested_state": "d1091f81158afe2bbadec72ce9c11dda616dbd123a0ebe18feb877753594b474",
  "output": "113 passed in 33.29s; exit 0. No cache provider or bytecode writes."
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "r2-adversarial-block-binding",
  "command": "$env:RECEIPTS_DIR='C:/Temp/agentic-framework/receipts'; $env:AGENT_MODEL_REGISTRY_HOME='P:/.agent'; $env:PYTHONDONTWRITEBYTECODE='1'; rtk proxy python -B C:/Temp/agentic-framework/receipts/dispatch/review-limits-exec-r2/reviewer_checks.py probes",
  "cwd": "P:/agentic-framework",
  "scope": "F-001 and related AC-8/AC-9/AC-13 boundary behavior",
  "phase": "targeted",
  "exit_code": 0,
  "result": "pass",
  "tested_state": "d1091f81158afe2bbadec72ce9c11dda616dbd123a0ebe18feb877753594b474",
  "output": "ADVERSARIAL_CASES_PASS 25. Same-slug 999/off requests refused with exit 1 and ledger_present=false for missing or matching alternate task and relative path; differing task refused carrier equality. Canonical-relative, offered alternate and plan-mode positives saved exactly offered limits. After-check mutation saved [9,21000000], not [999,\"off\"]. Load/check swap refused. Before-check edit refused binding/review_limits_differs. Partial/mismatched JSON refused; extra lines never changed saved limits. Tightening flags saved [7,12000]; loosening flag refused."
}
```

### Regenerated Full Evidence Binding

The independently calculated D6 identity is `d1091f81158afe2bbadec72ce9c11dda616dbd123a0ebe18feb877753594b474`, equal to H1-2 run 3 and the handoff. The run-3 summary reports identical before/after states and exit 0 for all 11 gates. Its 125-arm ledger selftest and 2235-test full run reflect the correction, superseding Round 1's 124/2234 results. Receipt bytes were hashed independently and decisive full output was read:

| Full check | Verified SHA-256 | Actual decisive output |
|------------|-----------------|------------------------|
| Full pytest | `bf043843561c6f38d59430efd3a53a911154c2301f617e0de6a4ef5ea2ea8cb7` | 2235 passed, 50 warnings, 36 subtests passed in 2030.31s |
| Staged credits pytest | `903218c8b25a3ea92b7ea8aeecb00b263bdc42ab7ff5ad876c830045dd162ad5` | 513 passed, 50 skipped, 1560 deselected, 50 warnings in 772.70s |
| Entire staged Pester gate | `1ec7bd58dc4695354f1a7ce9e560cc26e94b58f360cc3af394502500d5d10a18` | Result=Passed Passed=330 Failed=0 FailedBlocks=0 FailedContainers=0 Skipped=0 Uncovered=0 |

The staged ledger, verifier, both limits test files and review-limits config match the current core bytes. The staged credits module differs only by the normal project-name substitutions, which were directly inspected. Historical failures remain disclosed in the handoff. The previous intermittent Pester failure is not characterized as fixed; the new entire gate passes outright.

As specified by this plan, D6 hashes HEAD, porcelain status and Python version; it is **not a historical content fingerprint**. The before/after reviewer content snapshots independently show no repository content changed during this review. No evidence contradiction or affected-input change warranted repeating the 50-minute full gate or 15-minute Pester gate. Those suites were verified from the new receipts, not freshly rerun by this reviewer.

```json
{
  "schema_version": "evidence.v1",
  "check_id": "r2-full-evidence-binding",
  "command": "$env:RECEIPTS_DIR='C:/Temp/agentic-framework/receipts'; $env:AGENT_MODEL_REGISTRY_HOME='P:/.agent'; $env:PYTHONDONTWRITEBYTECODE='1'; rtk proxy python -B C:/Temp/agentic-framework/receipts/dispatch/review-limits-exec-r2/reviewer_checks.py identity",
  "cwd": "P:/agentic-framework",
  "scope": "Independent configured D6 identity, full receipt hashes and handoff durable evidence",
  "phase": "targeted",
  "exit_code": 0,
  "result": "pass",
  "tested_state": "d1091f81158afe2bbadec72ce9c11dda616dbd123a0ebe18feb877753594b474",
  "output": "D6_STATE d1091f81158afe2bbadec72ce9c11dda616dbd123a0ebe18feb877753594b474. Changed since Round 1: ledger, two limits test files, work handoff and copied Round 1 review only. All three passing full records have this exact state and independently matching receipt hashes (table above). durable_evidence.py --require-full --expected-state <independent state>: exit 0, OK: durable evidence records."
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "r2-repository-unchanged",
  "command": "$env:RECEIPTS_DIR='C:/Temp/agentic-framework/receipts'; $env:AGENT_MODEL_REGISTRY_HOME='P:/.agent'; $env:PYTHONDONTWRITEBYTECODE='1'; rtk proxy python -B C:/Temp/agentic-framework/receipts/dispatch/review-limits-exec-r2/reviewer_checks.py final",
  "cwd": "P:/agentic-framework",
  "scope": "Tracked and untracked non-ignored file content comparison and final configured D6 identity",
  "phase": "targeted",
  "exit_code": 0,
  "result": "pass",
  "tested_state": "d1091f81158afe2bbadec72ce9c11dda616dbd123a0ebe18feb877753594b474",
  "output": "REVIEWED_FILE_CONTENT_CHANGES []; D6_STATE_AFTER d1091f81158afe2bbadec72ce9c11dda616dbd123a0ebe18feb877753594b474. No repository files were edited; no commit was created."
}
```

### Remaining Findings

None. F-001 is fixed; no new finding survives verification.

### Verdict

`approved` — the execution achieves the registered intent. The only blocking Round 1 finding is closed, the affected behavior passes independent rechecks, and the regenerated full evidence is bound to the reviewed state. No corrections workflow was started. This receipt-local rolling artifact is ready for the implementing agent to copy into the canonical handoff location after dispatch.

🕐 Completed: 2026-10-21 04:16 (EDT)
