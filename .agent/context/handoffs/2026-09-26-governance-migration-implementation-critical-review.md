---
date: "2026-09-26"
review_mode: "execution"
target_plan: "docs/execution/plans/2026-09-26-governance-migration/implementation-plan.md"
loop_id: "governance-migration-2026-09-26"
round: 2
verdict: "approved"
intent_achieved: "yes"
findings_count: 0
blocking_findings_count: 0
template_version: "2.2"
requested_verbosity: "standard"
agent: "external-astra-reviewer"
---

# Critical Review: governance migration

## Intent Anchor

Make the approved governance migration reusable for new projects while preserving its required controls and generic project identity.

The intent is partially achieved. The new evidence and adoption contracts are useful, but manual verdicts fail in the real output-consumer chain and generic prose introduces an additional packaging-gate failure.

## Findings

| # | Severity | Blocking | Kind | Finding | File:Line | Recommendation | Status |
|---|---|---|---|---|---|---|---|
| F1 | High | yes | behavior | AC-4: Manual review observations cannot survive the shipped dispatch pipeline. A valid procedure/observer/exit_code:null checklist passed the v2 schema and review_ledger.load_verdict; running the actual strip-nulls command (exit 0) removed exit_code, after which both rejected it. Both wrappers always perform this stripping before post-validation. The new manual-validation contract therefore fails for legitimate non-software reviews. | core/.agent/schemas/review-verdict.schema.v2.json:166; core/tools/adapt_output_schema.py:170; core/tools/Invoke-CodexDispatch.ps1:1173; core/tools/Invoke-CodexDispatch.sh:912 | Preserve semantically required null values through schema adaptation and output normalization. Add an end-to-end manual-verdict fixture through the actual adapter and downstream schema/ledger loader, alongside command and malformed-manual negatives. | open |
| F2 | Medium | yes | behavior | AC-1: The cleanup makes read-only package verification fail on ordinary generic prose. remaining_source_hits now matches Source Project case-insensitively, flagging the two existing phrases "source project's name" in UPDATE-CHECKLIST.md. apply_forward makes zero replacements for either phrase, but --verify exits 2 with two raw-source hits. This is an additional migration-introduced gate failure, independent of the protected model pin and the unavailable live-registry checker. | scripts/placeholders.py:258; UPDATE-CHECKLIST.md:208; UPDATE-CHECKLIST.md:424 | Resolve the collision between the generic fixture identity and descriptive prose, without excluding the whole document or weakening real slug/identifier detection. Add ordinary-prose acceptance and six-form conversion/leak/idempotence regressions, then rerun read-only verification and report all remaining gate failures. | open |
| F3 | Medium | no | control-defeat | The command checklist branch still accepts a pass with command and evidence but no exit_code. Both the schema and review_ledger.load_verdict accepted {check:"full tests",result:"pass",command:"python -m pytest",evidence:"25 passed"}. The newly edited branch constrains exit_code only when present. This omission is inherited from the base schema, so it is recorded as a non-blocking follow-up rather than a migration-introduced failure. mechanism: verdict-to-state-transition | core/.agent/schemas/review-verdict.schema.v2.json:164; core/tools/review_ledger.py:614 | Require exit_code in the command branch and add a missing-exit negative at the schema and downstream loader boundary; retain the separate null-exit manual branch. | open |

All findings have High confidence and concern the framework deliverable. F1/F2 are executable contract failures, not stylistic or review-scaffolding objections. F1 meets the workflow's High-severity blocking threshold. F2 is a smaller required-gate defect with blocking separate from severity. F3 is inherited behavior and does not determine this verdict.

## Scope

One review-only dispatch, round 1. Reviewed the named handoff including the cleanup addendum, implementation plan, task record, rule-preservation ledger, release checklist, generic migration proposal, execution-review workflow, review template/schema and closed mechanism vocabulary. Compared the working tree against base `59a42fb37a4f66ab0ecef3613a91bfb640c5c571`, including direct reads of the three new implementation/test files, all new migration artifacts, the renamed research report and changed identity/link/schema/reference exceptions. The base-to-working-tree diff was captured with exit 0 (273,887 bytes); untracked files were inspected separately. The September 26 proposal was untracked at base, so its rename cannot be independently reconstructed from that commit; its current generic contents and links were inspected.

This authoring repository stores adoption templates under `core/`; its placeholders are intentional. Historical anonymized source-machine citations are illustrative, not links to another repository to open. No other project's repository was accessed. M0-M3 and local M5 are in scope. M4 hooks/scanners and advanced snapshot/lease adapters remain explicitly deferred.

**Reviewer identity and exception.** Reviewer is OpenAI Codex in a separate context, ledger agent `external-astra-reviewer`; producer is OpenAI / `codex-framework-implementor`. Requested dispatch model/effort is `gpt-6-astra` / `high`; routing is not independently attested inside this review. The human explicitly authorized: **"I authorize a **one-off same-vendor exception**"**. It applies only to this round. Per dispatch, the temporary registry copy removes only vendor-distinctness and the shared registry is unchanged; the reviewer neither changed nor separately audited registry contents. This is same-vendor separate-context review, never cross-vendor review. All other evidence, ledger and sandbox controls remain applicable. No nested dispatch, product correction, commit, push, global configuration change or loop mutation was performed. Ledger selftests used their disposable fixtures only.

**Protected changes.** The planted pin remains at `core/AGENTS.md:86`. The untracked working-context REVIEW-TEMPLATE remains untouched (observed SHA-256 `6a60e25354a87c226d258720d441ff77aeb5d4d1b3bd6afaab11eb5ee4373980`). Neither was allowlisted or corrected. The pin is a known release condition, not a migration-introduced finding.

## Evidence and current input identity

Independent before/after hashing reproduced `sha256:8d15413d52dead56ff1f098c49beeb30e4faee169d06e2829eaae4718d34899d`, matching the cleanup addendum, not the older migration hash. Algorithm: sort relative POSIX paths for all files in `core/` and `scripts/`, excluding `__pycache__` and `.pytest_cache`, plus ADOPTION-GUIDE, ADOPTION-QUESTIONS, PROJECT-PROFILE-TEMPLATE and UPDATE-CHECKLIST; hash each UTF-8 path, NUL, raw file bytes, NUL. The same result held after the fresh suite, adversarial probes and release checks. This is the declared local code/document identity; it does not hash environment or certify another platform. Maintainer review/proposal files were separately inspected and are outside this input set.

Observed environment: Python 3.14.7 (64-bit Windows), pytest 9.1.1, jsonschema 4.26.0; PowerShell and Git Bash available. Child checks disabled bytecode writes and pytest's cache provider; disposable files were under the reviewer scratch directory. Each child returncode was saved before reading output. Driver exit 0 means the driver finished; individual child failures remain explicit below.

The first suite run inherited RECEIPTS_DIR as the parent migration scratch root. Its human-decision fixture was therefore correctly rejected as a scratch citation: 1 failed, 24 passed, 30 subtests passed. A fresh complete rerun kept all files in the authorized scratch directory but set the *simulated adopter's* RECEIPTS_DIR to a distinct child directory. It passed 25 tests and 30 subtests. This is fixture isolation, not disabling the gate or changing repository files.

## Checklist Results

### Implementation and documentation review

| Contract | Result | Observation |
|---|---|---|
| AC-1 | partial | Read-only byte preservation, real raw-slug rejection and installed template aliases pass; all six canonical conversions are idempotent. Ordinary-prose source detection fails (F2). Reference scan is clean. |
| AC-2 | pass with inherited note | Durable evidence survives receipt deletion; malformed/missing output/exit, scratch-only evidence, stale/partial full claims and invalid blocked records have negative tests. Both normal task/handoff CLI consumers reject missing decision/block proof. F3 concerns inherited review-checklist behavior. |
| AC-3 | pass | Current roots fit budgets and registry headings match. Human/egress/review/profile/ledger controls survive the semantic comparison below. |
| AC-4 | fail | Static/targeted/fresh-full and manual/not_run evidence forms are distinct in the new validator. Manual review schema passes alone but fails after the actual adapter (F1). |
| AC-5 local | pass within stated limits | Disposable adoption, custom paths/spaces, preservation, wrapper path snippets and no-RTK exit propagation pass. Restricted-egress assertions are instruction/profile tests, not live model behavior. Native/live certification remains unmeasured. |

IR-1/IR-6: exercised the real local validator/adapter/installer functions and consumer CLIs, including positive and negative cases. IR-2/IR-3 API-stub/error-mapping checks are not applicable to this governance/tooling change. IR-4 is first-round generalization, with both dispatch wrappers and both blocked-row consumers inspected. IR-7: all five ACs are present; deferred M4/native certification was not misclassified as unfinished scoped code. DR-1 through DR-8: checked claims, renamed links, freshness, actual outputs, and release limitations; historical pre-cleanup results were not treated as current.

### Test rigor audit (IR-5)

| File / tests | Rating | Reason / limits |
|---|---|---|
| test_governance_migration.py: verify_reports_source_leak_without_writing | Strong for its unit boundary | Asserts exact unchanged CRLF bytes and nonzero leak result; mocks only orthogonal registry/reference gates. Does not cover generic-prose false positives (F2). |
| adopted_template_alias_requires_shipped_target; template_links_resolve_in_installed_location; unrelated_missing_tool_stays_unresolved | Strong | Positive resolution paired with missing-target refusal; installed-location path expectation is explicit. |
| model_prose_gate_separates_history_from_shipped_context | Strong | Real temporary trees distinguish maintainer history from shipped instructions. |
| live_slug_report_excludes_only_maintainer_history | Adequate | Checks filtering with a mocked upstream report; not a live registry certification. |
| root_instruction_budgets_allow_adoption_headroom; registry_matches_root_headings | Strong for mechanical properties | Actual instantiated strings/bytes and exact heading-set/cardinality equality; semantic rule preservation remains a manual audit. |
| full_copy_spaces_custom_roots_and_manual_evidence | Strong for local adoption | Copies and instantiates real tools/templates, preserves adopter-owned files, runs installed evidence CLI and stale-state negative. Egress/no-MEU profile text alone is not live enforcement evidence. |
| powershell_wrapper_path_contract_without_provider | Strong for extracted path code | Actual shipped snippets check repo/receipt prompts, cwd/schema/output containment, wildcard, prefix sibling, collision and junction rejection; no provider process. |
| bash_wrapper_path_contract_without_provider | Adequate | Actual shipped snippets and four cases on Git Bash; narrower coverage than PowerShell and no native Linux/macOS claim. |
| native_shell_receipt_read_preserves_nonzero_without_rtk | Strong on this host | Real child exit 7 and decisive receipt checked in both available shells. Missing-shell branches would not certify absent platforms. |
| test_durable_evidence.py: survives_receipt_removal; missing_and_malformed_records_refused; exit_result_consistency_and_red; real_placeholder_scan_output_is_not_an_unfilled_record | Strong | Real bytes/records and accept/refuse pairs, including integer-vs-bool distinction and meaningful literal scan output. |
| full_gate_cannot_be_partial_reused_or_stale; scratch_command_allowed_but_output_citation_refused; manual_procedure_has_no_fabricated_exit; not_run_distinguished_from_execution; windows_scratch_paths_are_checked_after_json_decoding | Strong at evidence.v1 boundary | Concrete state mismatch, receipt boundaries, manual/null, not_run/nonzero and decoded Windows cases. These do not cover review-output normalization. |
| closeout_consumer_rejects_scratch_only_handoff; blocked_predicate_rejects_ticket_only_and_accepts_decision; external_block_requires_actual_command_exit_and_error | Strong | Actual subprocess closeout plus predicate positive/negative cases; additional reviewer probes exercised the full handoff and task CLI paths. |
| test_review_verdict_schema_v2.py: all 26 parameter arms | Adequate | Real validator accepts and rejects substantive shapes. Manual tests stop at the schema and therefore miss F1; absent command exit has no negative arm (F3). |

No changed test merely mirrors an implementation value as its only oracle. Green isolated tests do not establish the missing adapter integration. Existing task/closeout/ledger selftests include must-accept arms so blanket refusal would fail them.

### Semantic rule-preservation audit

Compared base AGENTS/GUARDRAILS/CLAUDE against current text and rule-preservation.md. Authority and Approval plus SIGN 1/3 retain explicit human authorization, untrusted-approval provenance, plan/execution separation, human-vs-reviewer-auto transition and no automatic commits. Independent Review retains vendor separation, no self-approval, live capability resolution and kind/intent/author/vendor/usage/budget obligations; this round's human exception does not modify that policy. Session/Profile, Validation Pipeline and command registration retain C egress precedence, B4 named-human fallback, D6-owned commands and D9=no. The new Execution Contract retains completed/validly-blocked rows, independent approval, structural closeout, H1-review-H2 order and ledger stop/continuation obligations. Root section inventory matches all twelve current H2 headings.

The ledger openly records deliberate changes: actual host instruction hierarchy, bounded review resources, optional product coverage/runtime choices, independently reviewed specification amendments, compaction as continuation and removing duplicate full reruns. These are approved migrations, not accidental rule losses. No new hook/lease/snapshot enforcement was inferred. CLAUDE retains explicit AGENTS/GUARDRAILS imports; actual loader behavior remains a release probe.

### Commands and decisive observations

These are actual child commands or observed manual procedures. Output is pasted below; external receipts are not needed to interpret the results. In a JSON evidence block, result `fail` reflects the child command's nonzero status; a zero-exit diagnostic probe instead has `pass` for execution while its output demonstrates the product failure. The checklist's semantic result may therefore be `fail` with driver exit 0.

```json
{
  "schema_version": "evidence.v1",
  "check_id": "review-1",
  "cwd": ".",
  "scope": "Fresh complete pytest suites, isolated fixture receipt root",
  "phase": "full",
  "result": "pass",
  "tested_state": "sha256:8d15413d52dead56ff1f098c49beeb30e4faee169d06e2829eaae4718d34899d",
  "exit_code": 0,
  "output": "25 passed, 30 subtests passed in 8.80s. Child environment set TMP/TEMP to reviewer scratch, disabled bytecode/cache writes, and set RECEIPTS_DIR to a distinct simulated receipt root. Current code/document input hash remained sha256:8d15413d52dead56ff1f098c49beeb30e4faee169d06e2829eaae4718d34899d.",
  "command": "rtk proxy C:\\Python314\\python.exe -B -X utf8 -m pytest scripts/tests core/tools/tests -q -p no:cacheprovider --basetemp C:\\Temp\\agentic-framework-migration\\reviewer\\pytest-isolated",
  "fresh": true,
  "snapshot": false
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "review-2",
  "cwd": ".",
  "scope": "Initial pytest run under inherited receipt-root setting",
  "phase": "targeted",
  "result": "fail",
  "tested_state": "sha256:8d15413d52dead56ff1f098c49beeb30e4faee169d06e2829eaae4718d34899d",
  "exit_code": 1,
  "output": "1 failed, 24 passed, 30 subtests passed. The existing-file decision fixture was inside inherited RECEIPTS_DIR, so the durable-link predicate correctly refused it as scratch. Isolating the simulated receipt root made the complete suite pass; no repository change was made.",
  "command": "rtk proxy C:\\Python314\\python.exe -B -X utf8 -m pytest scripts/tests core/tools/tests -q -p no:cacheprovider --basetemp C:\\Temp\\agentic-framework-migration\\reviewer\\pytest"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "review-3",
  "cwd": ".",
  "scope": "Reference and tool resolution",
  "phase": "targeted",
  "result": "pass",
  "tested_state": "sha256:8d15413d52dead56ff1f098c49beeb30e4faee169d06e2829eaae4718d34899d",
  "exit_code": 0,
  "output": "Required-dangling=0; unresolved=0; unclassified=0.",
  "command": "rtk proxy C:\\Python314\\python.exe -B -X utf8 scripts/refcheck.py --all"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "review-4",
  "cwd": ".",
  "scope": "Sanitizer model-prose selftest",
  "phase": "targeted",
  "result": "pass",
  "tested_state": "sha256:8d15413d52dead56ff1f098c49beeb30e4faee169d06e2829eaae4718d34899d",
  "exit_code": 0,
  "output": "12 arms, 0 failures; this selftest covers model prose, not the generic source-token collision.",
  "command": "rtk proxy C:\\Python314\\python.exe -B -X utf8 scripts/sanitize.py --selftest"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "review-5",
  "cwd": ".",
  "scope": "Installer selftest",
  "phase": "targeted",
  "result": "pass",
  "tested_state": "sha256:8d15413d52dead56ff1f098c49beeb30e4faee169d06e2829eaae4718d34899d",
  "exit_code": 0,
  "output": "32 arms, 0 failures.",
  "command": "rtk proxy C:\\Python314\\python.exe -B -X utf8 scripts/instantiate.py --selftest"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "review-6",
  "cwd": ".",
  "scope": "Task validator selftest",
  "phase": "targeted",
  "result": "pass",
  "tested_state": "sha256:8d15413d52dead56ff1f098c49beeb30e4faee169d06e2829eaae4718d34899d",
  "exit_code": 0,
  "output": "50 arms, 0 failures; 14 must-OK.",
  "command": "rtk proxy C:\\Python314\\python.exe -B -X utf8 core/tools/lint_task_contract.py --selftest"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "review-7",
  "cwd": ".",
  "scope": "Closeout validator selftest",
  "phase": "targeted",
  "result": "pass",
  "tested_state": "sha256:8d15413d52dead56ff1f098c49beeb30e4faee169d06e2829eaae4718d34899d",
  "exit_code": 0,
  "output": "59 arms, 0 failures; 19 must-OK.",
  "command": "rtk proxy C:\\Python314\\python.exe -B -X utf8 core/tools/validate_closeout_artifacts.py --selftest"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "review-8",
  "cwd": ".",
  "scope": "Ledger isolated selftest",
  "phase": "targeted",
  "result": "pass",
  "tested_state": "sha256:8d15413d52dead56ff1f098c49beeb30e4faee169d06e2829eaae4718d34899d",
  "exit_code": 0,
  "output": "105 arms, 0 failures; 53 must-OK; only disposable selftest loops.",
  "command": "rtk proxy C:\\Python314\\python.exe -B -X utf8 core/tools/review_ledger.py selftest"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "review-9",
  "cwd": ".",
  "scope": "Schema adapter existing selftest",
  "phase": "targeted",
  "result": "pass",
  "tested_state": "sha256:8d15413d52dead56ff1f098c49beeb30e4faee169d06e2829eaae4718d34899d",
  "exit_code": 0,
  "output": "24 arms, 0 failures; does not cover the new manual-verdict round trip.",
  "command": "rtk proxy C:\\Python314\\python.exe -B -X utf8 core/tools/adapt_output_schema.py selftest"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "review-10",
  "cwd": ".",
  "scope": "Actual adapter and generic-source probes",
  "phase": "targeted",
  "result": "pass",
  "tested_state": "sha256:8d15413d52dead56ff1f098c49beeb30e4faee169d06e2829eaae4718d34899d",
  "exit_code": 0,
  "output": "Probe driver completed. Manual verdict valid before normalization, invalid afterward; actual strip-nulls child exited 0 and removed one null key. All six canonical source forms converted and were idempotent. Two ordinary prose phrases each produced one leak and zero replacements. F1/F2.",
  "command": "rtk proxy python -B -X utf8 C:/Temp/agentic-framework-migration/reviewer/probes.py"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "review-11",
  "cwd": ".",
  "scope": "Downstream ledger loader and both blocked-row CLI consumers",
  "phase": "targeted",
  "result": "pass",
  "tested_state": "sha256:8d15413d52dead56ff1f098c49beeb30e4faee169d06e2829eaae4718d34899d",
  "exit_code": 0,
  "output": "Both task and full handoff checks accepted valid decision evidence (0) and rejected absent decision targets or blocks (1). Ledger loader accepted valid manual evidence and refused stripped manual evidence; it accepted a command pass missing its exit (F3). Working-tree identity scan: 181 non-cache/non-Git files, zero retired-name hits and no unreadable included files. No ledger record/begin/continue operation occurred.",
  "command": "rtk proxy python -B -X utf8 C:/Temp/agentic-framework-migration/reviewer/consumer_probes.py"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "review-12",
  "cwd": ".",
  "scope": "Read-only release sanitizer",
  "phase": "targeted",
  "result": "fail",
  "tested_state": "sha256:8d15413d52dead56ff1f098c49beeb30e4faee169d06e2829eaae4718d34899d",
  "exit_code": 2,
  "output": "Exit 2: two raw-source hits in UPDATE-CHECKLIST.md; model checker unavailable in this dispatch registry configuration; protected core/AGENTS.md:86 pin also reported by prose gate; references/tool classifications clean. Input hash unchanged. Do not interpret this as a pin-only failure.",
  "command": "rtk proxy C:\\Python314\\python.exe -B -X utf8 scripts/sanitize.py --verify"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "review-13",
  "cwd": ".",
  "scope": "Reference selftest execution availability",
  "phase": "targeted",
  "result": "fail",
  "tested_state": "sha256:8d15413d52dead56ff1f098c49beeb30e4faee169d06e2829eaae4718d34899d",
  "exit_code": 1,
  "output": "Could not execute its arms: copytree hit WinError 5 on the repository .pytest_cache directory. No successful selftest result claimed; ordinary --all scan passed.",
  "command": "rtk proxy C:\\Python314\\python.exe -B -X utf8 scripts/refcheck.py --selftest"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "review-14",
  "cwd": ".",
  "scope": "adoption-wp1",
  "phase": "targeted",
  "result": "pass",
  "tested_state": "sha256:8d15413d52dead56ff1f098c49beeb30e4faee169d06e2829eaae4718d34899d",
  "exit_code": 0,
  "output": "OK: wp1 layout, locators, and EGRESS_PRECEDENCE",
  "command": "rtk proxy C:\\Python314\\python.exe -B -X utf8 scripts/tests/test_adoption_contract.py --case wp1"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "review-15",
  "cwd": ".",
  "scope": "adoption-templates-installed",
  "phase": "targeted",
  "result": "pass",
  "tested_state": "sha256:8d15413d52dead56ff1f098c49beeb30e4faee169d06e2829eaae4718d34899d",
  "exit_code": 0,
  "output": "OK: TEMPLATE_HOME consumers",
  "command": "rtk proxy C:\\Python314\\python.exe -B -X utf8 scripts/tests/test_adoption_contract.py --case templates-installed"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "review-16",
  "cwd": ".",
  "scope": "adoption-d9-no",
  "phase": "targeted",
  "result": "pass",
  "tested_state": "sha256:8d15413d52dead56ff1f098c49beeb30e4faee169d06e2829eaae4718d34899d",
  "exit_code": 0,
  "output": "OK: D9_NO_BRANCH present",
  "command": "rtk proxy C:\\Python314\\python.exe -B -X utf8 scripts/tests/test_adoption_contract.py --case d9-no"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "review-17",
  "cwd": ".",
  "scope": "adoption-d6",
  "phase": "targeted",
  "result": "pass",
  "tested_state": "sha256:8d15413d52dead56ff1f098c49beeb30e4faee169d06e2829eaae4718d34899d",
  "exit_code": 0,
  "output": "OK: D6_ADOPTER_ARGV and no mcp-audit",
  "command": "rtk proxy C:\\Python314\\python.exe -B -X utf8 scripts/tests/test_adoption_contract.py --case d6"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "review-18",
  "cwd": ".",
  "scope": "adoption-profile-permissions",
  "phase": "targeted",
  "result": "pass",
  "tested_state": "sha256:8d15413d52dead56ff1f098c49beeb30e4faee169d06e2829eaae4718d34899d",
  "exit_code": 0,
  "output": "OK: profile slots and permission behavior",
  "command": "rtk proxy C:\\Python314\\python.exe -B -X utf8 scripts/tests/test_adoption_contract.py --case profile-permissions"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "review-19",
  "cwd": ".",
  "scope": "AC-3 semantic preservation and local AC-5 coverage audit",
  "phase": "manual",
  "result": "pass",
  "tested_state": "sha256:8d15413d52dead56ff1f098c49beeb30e4faee169d06e2829eaae4718d34899d",
  "exit_code": null,
  "output": "Human authorization, egress-first human review, no self-approval, profile-owned D6/D9 commands, and ledger kind/intent/vendor/usage/budget obligations remain. Root budgets and registry equality have executable tests. Tests measure Windows/PowerShell and Git Bash snippets plus disposable adoption; native Linux/macOS, real instruction loading, and live provider behavior remain unmeasured.",
  "procedure": "Compare baseline root rules, the preservation ledger, current roots/registry, changed workflows/templates, and the assertions in every changed or new test file; inspect the new and renamed files directly.",
  "observer": "external-astra-reviewer (OpenAI Codex)"
}
```

### F1 / F3 decisive reproduction

Actual command: `rtk proxy python -B -X utf8 C:/Temp/agentic-framework-migration/reviewer/probes.py` (driver exit 0), followed by `consumer_probes.py` (driver exit 0). The first script invoked the actual `core/tools/adapt_output_schema.py strip-nulls` child and preserved its exit 0; the second called the ledger's read-only `load_verdict`, never record/begin/reopen. Decisive output:

```text
MANUAL BEFORE ADAPTER True
ADAPTER ... EXIT 0 OK: removed 1 null-valued key(s) from manual-verdict.json
MANUAL AFTER ADAPTER False
LEDGER VALID MANUAL None
LEDGER STRIPPED MANUAL REFUSED: verdict does not validate against the v2 schema:
  checklist_results/0: {...procedure..., observer..., evidence...} is not valid under any of the given schemas.
LEDGER MISSING COMMAND EXIT ACCEPTED:
  [{"check":"full tests","result":"pass","command":"python -m pytest","evidence":"25 passed"}]
```

Self-contained input for reproducing the manual failure (write it only to disposable storage, then run the actual adapter's `strip-nulls` on that copy and validate against the shipped schema):

```json
{
  "schema_version":"review-verdict.v2", "date":"2026-09-26",
  "review_mode":"execution", "loop_id":"probe-only", "round":1,
  "target_plan":"probe-plan.md", "agent":"probe-reviewer",
  "requested_verbosity":"standard", "verdict":"approved", "summary":"probe",
  "intent_anchor":"Probe a manual observation.", "intent_achieved":"yes",
  "findings":[],
  "checklist_results":[{
    "check":"citation audit", "result":"pass",
    "procedure":"Compare all eight citations against the approved manuscript",
    "observer":"named reviewer", "exit_code":null, "evidence":"8 citations matched"
  }]
}
```

The specimen is synthetic probe input, not an approval of this migration. `Draft202012Validator(schema).is_valid(input)` is true. After `strip-nulls`, it is false because exit_code is absent. `review_ledger.load_verdict(path)` reproduces the same acceptance/refusal. For F3, replace the checklist with the exact four-field command row above; both validators accept it without an exit. The base schema also lacks a command-exit requirement, establishing why F3 is inherited. Both shipped wrappers normalize before validation at the cited lines; no live provider is needed to exercise that deterministic failure.

### F2 and generic cleanup

```text
GENERIC CONVERSION github.com/example/source-project -> {{REPO_URL}}; hits 0; idempotent True
GENERIC CONVERSION C:/Temp/source-project -> {{RECEIPTS_DIR}}; hits 0; idempotent True
GENERIC CONVERSION P:/source-project -> {{PROJECT_ROOT}}; hits 0; idempotent True
GENERIC CONVERSION SOURCE_PROJECT -> {{PROJECT_NAME_UPPER}}; hits 0; idempotent True
GENERIC CONVERSION Source Project -> {{PROJECT_NAME_TITLE}}; hits 0; idempotent True
GENERIC CONVERSION source-project -> {{PROJECT_NAME}}; hits 0; idempotent True
ORDINARY PROSE "The source project's name": leaks 1, replacements 0
ORDINARY PROSE "a drive letter is not the source project's name.": leaks 1, replacements 0
```

Those results came directly from `placeholders.apply_forward` and `remaining_source_hits`; repeating apply_forward on each converted value returned identical text and zero replacements. The release sanitizer independently reported `VERIFY FAILED: 1 file(s) still contain the raw slug: 2 UPDATE-CHECKLIST.md`, exit 2, with unchanged input hash. Its live model checker could not be located under this dispatch's temporary registry configuration, and its independent prose-model gate still reported the protected pin. Thus the current release check has a proven extra source-detection failure and an unavailable registry component; the older pin-only exit 4 is not current evidence.

The renamed September 18 report matches its baseline after generic identity substitution plus the explicit historical-path disclaimer. Both current generic research filenames and the changed internal references were inspected. The schema identifier and refcheck exception use the generic identity. A case-insensitive filename/byte scan over 181 included working files found zero retired-identity matches, with no unreadable included files. Git metadata and generated caches were excluded; this is not a claim about all cache bytes. Historical source paths were not dereferenced.

### Shared blocked-row consumer probes

The task probe used the linter's real ten-column fixture row with status `[B]`, row reference `B-1`, and `follow-up [decision](decision.md)`. The handoff used the validator's real two-AC fixture bound to a disposable `2026-09-01-demo-thing/implementation-plan.md`, with AC-2 referencing B-AC-2. Each had an existing local decision file and the matching block:

```text
### B-1
Reason: human-decision
Decision: [decision](decision.md)
```

The handoff used the corresponding B-AC-2 heading. The normal task CLI and normal `--handoff ... --plan ...` CLI each returned 0. Replacing only the Decision target with `absent.md` returned 1 for each; removing only the block also returned 1 for each. Decisive diagnostics were `human decision needs Decision: and a durable decision link` and `missing ### B-<id> evidence block`. An initial exploratory `--handoff-structure-only` call returned 0 for these block mutations, as expected for that explicitly narrower entry point; the full consumer checks above establish the claimed shared contract.

## Remaining release conditions and unavailable checks

- Protected pin disposition remains with its owner. This review did not remove it or use it to mask F2.
- `refcheck.py --selftest` exited 1 before its arms: `shutil.copytree` could not read the sandbox-restricted root `.pytest_cache` (WinError 5). Ordinary `refcheck.py --all` did pass. No cache permission/configuration change was attempted.
- Live model-slug checker unavailable in the temporary dispatch registry configuration. This is an environment limitation, not proof that the model-slug gate passed.
- Native Linux/macOS adoption, actual instruction-loader/import composition and live provider/sandbox certification remain unmeasured. Windows, PowerShell, Git Bash and POSIX-shaped fixtures establish only their stated local scope.
- M4 hooks/scanners and advanced snapshot/lease adapters remain outside this approved slice. No additional enforcement prerequisite was invented.

## Verdict

**changes_required; intent_achieved: partial.** F1 and F2 must be corrected to complete the scoped reusable migration. F3 is an inherited non-blocking observation. Passing tests and the preserved core controls do not cure the demonstrated output-consumer and packaging failures. This one-off dispatch ends with findings; it does not start a correction loop, authorize a commit/release, or mutate the review ledger.

Canonical review: `.agent/context/handoffs/2026-09-26-governance-migration-implementation-critical-review.md`.

🕐 Completed: 2026-09-26 12:34 (EDT)


## Orchestrator dispatch receipt (round 1)

Recorded at 2026-09-26T16:39:35.730101+00:00. This addendum records dispatch transport and ledger checks;
the reviewer-authored findings and verdict above are unchanged.

- Wrapper metadata confirms `model=gpt-6-astra`, `reasoning_effort=high`,
  `author_vendor=openai`, child exit 0 and one `turn.completed` event.
- The explicit human same-vendor exception applied only to this round. The shared
  registry and resolver module hashes still match their pre-dispatch values. The
  local exception is marked consumed and the launcher refuses another use.
- Repository before/after file hashing found only this canonical review changed;
  no implementation, plan, original handoff or protected user file was edited.
- Wrapper exit was **1**, because F1 also affected this review's own manual
  observation: normalization deleted `checklist_results/14/exit_code: null`.
  Original raw response, normalized response and failed status are preserved.
- A separate validated copy restores exactly that null from the untouched raw
  response. No finding, recommendation, verdict or observation was rewritten.
  Full v2 schema validation passed, followed by successful ledger recording with
  the original event-log usage receipt. Wrapper failure is not relabeled success.

Recovery command: `rtk proxy python -X utf8 C:/Temp/agentic-framework-migration/recover_review_verdict.py`.
Preserved exit: **0**. Decisive output:

```text
Recovered exactly one required null from raw model output; full v2 schema validation passed; verdict and findings unchanged.
```

Ledger command: `rtk proxy pwsh -NoProfile -File C:/Temp/agentic-framework-migration/record_recovered_review.ps1`.
The script sets the dispatch receipt root and invokes the unmodified ledger's
`record` command for this loop with the validated verdict and original events.
Preserved exit: **0**. Decisive output:

```text
OK: recorded round 1 verdict=changes_required agent='external-astra-reviewer' blocking=2 intent_achieved=partial usage=5,659,552
```

Result: round 1 is recorded with two blocking findings. No corrections or further
review round were executed. Implementation identity remains the hash documented above.


## Corrections Applied (2026-09-26, before round 2)

Status: **corrections_applied**, pending external re-review. The implementer does not approve this work.
The human extended the same-vendor exception: "continued exception is granted over all runs until approved".
This supersedes round 1's single-use limitation only for this migration loop. The shared registry remains unchanged.

| Finding | Correction | Verification |
|---|---|---|
| F1 | Both wrappers pass the original schema to null normalization. Declared optional fields that reject null are stripped; legitimate nullable fields, required fields and unknown fields remain for authoritative post-validation. The raw model response is copied byte-for-byte. Legacy schema-less normalization remains compatible. | Real adapter CLI followed by schema and ledger-loader checks: valid manual and command records survive; malformed manual and missing/null command exits fail. Required/unknown nulls are not silently repaired. |
| F2 | The fixture's proper-name form is now `ExampleSourceProject`; slug and environment identifier stay generic. Ordinary source-project prose is no longer confused with an identity. | Six forms convert/detect and remain idempotent; ordinary prose passes read-only sanitizer verification; actual package verify reports zero raw source slugs. |
| F3 | Command checklist branch now requires exit_code as well as command. | Missing-exit negative rejects both before normalization and through the downstream ledger loader. |

Tests were written before the fixes: 10 failed, 1 passed, 6 subtests passed. Initial green work exposed raw-backup newline conversion; the implementation was corrected without relaxing the byte-preservation assertion. Final targeted result: 11 passed, 6 subtests passed. The schema change is intentional; preserve round 1 and acknowledge the new instrument digest through the ledger's continue operation before round 2.

Full local run: 36 tests and 36 subtests pass. Reference checks, 16 refcheck arms, 12 sanitizer arms, 32 instantiation arms, 50 task arms, 59 closeout arms, 105 ledger arms, 24 adapter arms, and all five PowerShell encoding/parse checks pass. The actual release sanitizer exits 4 for the preserved model pin only (reported by both model checks); raw source hits=0, changed files=0, dangling references=0. No release certification, native-platform claim, commit or publication is added.

The following observations were captured after all code changes with identical before/after input hashes. Hashing uses the earlier documented NUL-separated path/byte algorithm. The checker used the real shared registry for the release scan, removed inherited RECEIPTS_DIR for independent fixture isolation, and disabled bytecode writes. Scratch output is not the sole evidence: decisive results are pasted below.

```json
{
  "schema_version": "evidence.v1",
  "check_id": "r2-pytest",
  "command": "rtk proxy C:\\Python314\\python.exe -B -X utf8 -m pytest scripts/tests core/tools/tests -q -p no:cacheprovider",
  "cwd": "P:/agentic-framework",
  "scope": "Full framework local regression suite",
  "phase": "full",
  "exit_code": 0,
  "result": "pass",
  "tested_state": "sha256:13349cf2c9fa1afa3eff1c25ba21cd577b2bbf8bcbbc2625c171f709d2387b4c",
  "output": "36 passed, 36 subtests passed in 10.68s",
  "fresh": true
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "r2-refcheck",
  "command": "rtk proxy C:\\Python314\\python.exe -B -X utf8 scripts/refcheck.py --all",
  "cwd": "P:/agentic-framework",
  "scope": "refcheck",
  "phase": "targeted",
  "exit_code": 0,
  "result": "pass",
  "tested_state": "sha256:13349cf2c9fa1afa3eff1c25ba21cd577b2bbf8bcbbc2625c171f709d2387b4c",
  "output": "  REQUIRED-DANGLING:        0\n  UNRESOLVED:               0\n  UNCLASSIFIED:             0",
  "fresh": true
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "r2-refcheck-selftest",
  "command": "rtk proxy C:\\Python314\\python.exe -B -X utf8 scripts/refcheck.py --selftest",
  "cwd": "P:/agentic-framework",
  "scope": "refcheck-selftest",
  "phase": "targeted",
  "exit_code": 0,
  "result": "pass",
  "tested_state": "sha256:13349cf2c9fa1afa3eff1c25ba21cd577b2bbf8bcbbc2625c171f709d2387b4c",
  "output": "RESULT: 16 arm(s) (7 must-pass), 0 failure(s)",
  "fresh": true
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "r2-sanitize-selftest",
  "command": "rtk proxy C:\\Python314\\python.exe -B -X utf8 scripts/sanitize.py --selftest",
  "cwd": "P:/agentic-framework",
  "scope": "sanitize-selftest",
  "phase": "targeted",
  "exit_code": 0,
  "result": "pass",
  "tested_state": "sha256:13349cf2c9fa1afa3eff1c25ba21cd577b2bbf8bcbbc2625c171f709d2387b4c",
  "output": "RESULT: 12 arm(s), 0 failure(s)",
  "fresh": true
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "r2-instantiate-selftest",
  "command": "rtk proxy C:\\Python314\\python.exe -B -X utf8 scripts/instantiate.py --selftest",
  "cwd": "P:/agentic-framework",
  "scope": "instantiate-selftest",
  "phase": "targeted",
  "exit_code": 0,
  "result": "pass",
  "tested_state": "sha256:13349cf2c9fa1afa3eff1c25ba21cd577b2bbf8bcbbc2625c171f709d2387b4c",
  "output": "RESULT: 32 arm(s), 0 failure(s) [32 passing this run; a validator that always raises cannot pass]",
  "fresh": true
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "r2-task-selftest",
  "command": "rtk proxy C:\\Python314\\python.exe -B -X utf8 core/tools/lint_task_contract.py --selftest",
  "cwd": "P:/agentic-framework",
  "scope": "task-selftest",
  "phase": "targeted",
  "exit_code": 0,
  "result": "pass",
  "tested_state": "sha256:13349cf2c9fa1afa3eff1c25ba21cd577b2bbf8bcbbc2625c171f709d2387b4c",
  "output": "  ok   no-receipt-without-configured-root-fails-closed want=3/FAIL-CLOSED got=3/FAIL-CLOSED\n  ok   missing-file-fails-closed want=3/FAIL-CLOSED got=3/FAIL-CLOSED\n  ok   no-table-fails-closed want=3/FAIL-CLOSED got=3/FAIL-CLOSED\n  ok   header-only-fails-closed want=3/FAIL-CLOSED got=3/FAIL-CLOSED\nRESULT: 50 arm(s), 0 failure(s) [14 must-OK arms, so the linter is not refusing everything]",
  "fresh": true
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "r2-closeout-selftest",
  "command": "rtk proxy C:\\Python314\\python.exe -B -X utf8 core/tools/validate_closeout_artifacts.py --selftest",
  "cwd": "P:/agentic-framework",
  "scope": "closeout-selftest",
  "phase": "targeted",
  "exit_code": 0,
  "result": "pass",
  "tested_state": "sha256:13349cf2c9fa1afa3eff1c25ba21cd577b2bbf8bcbbc2625c171f709d2387b4c",
  "output": "  ok   schema-without-fields-block-fails-closed want=3/FAIL-CLOSED got=3/FAIL-CLOSED\n  ok   absent-handoff-fails-closed want=3/FAIL-CLOSED got=3/FAIL-CLOSED\n  ok   absent-receipt-fails-closed want=3/FAIL-CLOSED got=3/FAIL-CLOSED\n  ok   receipt-missing-key-fails-closed want=3/FAIL-CLOSED got=3/FAIL-CLOSED\n  ok   receipt-wrong-schema-fails-closed want=3/FAIL-CLOSED got=3/FAIL-CLOSED\nRESULT: 59 arm(s), 0 failure(s) [19 must-OK arms, so the tool is not refusing everything]",
  "fresh": true
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "r2-ledger-selftest",
  "command": "rtk proxy C:\\Python314\\python.exe -B -X utf8 core/tools/review_ledger.py selftest",
  "cwd": "P:/agentic-framework",
  "scope": "ledger-selftest",
  "phase": "targeted",
  "exit_code": 0,
  "result": "pass",
  "tested_state": "sha256:13349cf2c9fa1afa3eff1c25ba21cd577b2bbf8bcbbc2625c171f709d2387b4c",
  "output": "PASS unparseable-verdict-fails-closed       FAIL-CLOSED\nPASS v42-unknown-key-fails-closed           FAIL-CLOSED\nPASS cli-failclosed-is-3                    3/FAIL-CLOSED\nPASS begin-missing-vocabulary-fails-closed  FAIL-CLOSED\nPASS payload-missing-fails-closed           FAIL-CLOSED\nPASS missing-usage-receipt-fails-closed     FAIL-CLOSED\nPASS unwritable-ledger-is-3-not-1           3/FAIL-CLOSED\nPASS no-receipts-dir-fails-closed           FAIL-CLOSED\nRESULT: 105 arm(s), 0 failure(s) [53 must-OK arms, so the tool is not refusing everything]",
  "fresh": true
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "r2-adapter-selftest",
  "command": "rtk proxy C:\\Python314\\python.exe -B -X utf8 core/tools/adapt_output_schema.py selftest",
  "cwd": "P:/agentic-framework",
  "scope": "adapter-selftest",
  "phase": "targeted",
  "exit_code": 0,
  "result": "pass",
  "tested_state": "sha256:13349cf2c9fa1afa3eff1c25ba21cd577b2bbf8bcbbc2625c171f709d2387b4c",
  "output": "PASS absent-schema -> 3 FAIL-CLOSED:  -- exit=3\nPASS malformed-schema -> 3 FAIL-CLOSED:  -- exit=3\nPASS malformed-document -> 3 FAIL-CLOSED: (file untouched)  -- exit=3\nPASS unwritable-destination -> 3 FAIL-CLOSED:  -- exit=3\nRESULT: 24 arm(s), 0 failure(s) [2 must-OK + 4 must-survive, so neither a stripper that deletes everything nor one that deletes nothing can pass this suite]",
  "fresh": true
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "r2-ps1-encoding",
  "command": "rtk proxy C:\\Python314\\python.exe -B -X utf8 scripts/tests/test_ps1_encoding.py",
  "cwd": "P:/agentic-framework",
  "scope": "ps1-encoding",
  "phase": "targeted",
  "exit_code": 0,
  "result": "pass",
  "tested_state": "sha256:13349cf2c9fa1afa3eff1c25ba21cd577b2bbf8bcbbc2625c171f709d2387b4c",
  "output": "OK: 5 core/**/*.ps1 ASCII-or-BOM; wrapper parse-only + usage\n[rtk] /!\\ No hook installed \u2014 run `rtk init -g` for automatic token savings",
  "fresh": true
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "r2-release-sanitize",
  "command": "rtk proxy C:\\Python314\\python.exe -B -X utf8 scripts/sanitize.py --verify",
  "cwd": "P:/agentic-framework",
  "scope": "release-sanitize",
  "phase": "targeted",
  "exit_code": 4,
  "result": "fail",
  "tested_state": "sha256:13349cf2c9fa1afa3eff1c25ba21cd577b2bbf8bcbbc2625c171f709d2387b4c",
  "output": "  mode:            VERIFY (read-only)\n  VERIFY FAILED:   model-slug (tier-1): 1 hit(s):\n  VERIFY FAILED:   prose model name (tier-1): 1 hit(s):",
  "fresh": true
}
```


## Recheck (2026-09-26)

**Round 2 — approved; intent_achieved: yes.** Current findings: **0 open, 0 blocking; F1/F2/F3 fixed**. This section supersedes the round-1 verdict and pending-corrections status above; their evidence and history remain unchanged.

### Intent, scope and reviewer identity

Make the approved governance migration reusable for new projects while preserving its required controls and generic project identity.

Rechecked F1/F2/F3 and their changed consumers: the adapter, both dispatch wrappers, v2 schema, output-pipeline tests, placeholder rules and packaging regressions. Read the ACs, rule-preservation ledger and execution-review materiality rules. The unchanged broader migration evidence remains applicable at the independently matched input identity below. No unrelated historical-document search or broad-suite rerun was used to manufacture a fresh summary.

Reviewer: **external-astra-reviewer**, OpenAI, separate context. Producer: **codex-framework-implementor**, OpenAI. Requested model/effort: **gpt-6-astra / high**; dispatch routing is not independently attested from inside this review. The human's continued same-vendor exception is explicitly recorded: **"continued exception is granted over all runs until approved"**. It applies to this migration loop, superseding round 1's single-use limit. This is **same-vendor separate-context review, not cross-vendor independence**. Per the dispatch contract, its local registry copy removes only vendor-distinctness; the shared registry is unchanged. The reviewer made no registry/configuration changes and did not independently recertify the exception-copy construction. All other review controls remain applicable.

### Prior findings recheck

| Finding | Prior status | Current status | Evidence and current locations |
|---|---|---|---|
| F1 | Open, blocking, High | **fixed** | `core/tools/adapt_output_schema.py:158` removes only directly declared optional fields rejecting null. Meaningful nullable exits, required nulls and unknown nulls survive; invalid evidence then fails the real consumers. `:237` reads raw bytes and `:263` writes the exact backup. Both `core/tools/Invoke-CodexDispatch.ps1:1173` and `core/tools/Invoke-CodexDispatch.sh:912` pass the original schema, not the API adaptation. Valid manual and command verdicts passed real CLI normalization, schema CLI and ledger loading; malformed cases were refused. |
| F2 | Open, blocking, Medium | **fixed** | `scripts/placeholders.py:32` names the unambiguous `ExampleSourceProject`; `:254` retains case-insensitive title, slug and identifier detection. Six-form conversion/detection/idempotence and ordinary prose acceptance pass, paired with a read-only raw-leak refusal. Actual package scan reports zero raw slugs, zero changes and zero dangling references. |
| F3 | Open, non-blocking, Medium | **fixed** | `core/.agent/schemas/review-verdict.schema.v2.json:164` requires command and integer exit_code. Missing, null, string and boolean command exits fail schema CLI and `review_ledger.load_verdict` after normalization; missing exit is also rejected before normalization by the shipped regression. Historical mechanism remains `verdict-to-state-transition`; no new recurrence is asserted. |

No remaining findings. The planted pin is the already-declared release condition, not a migration-introduced defect or a new finding.

### Independent evidence

All commands below ran from `P:/agentic-framework`. Python children used `-B -X utf8`, TEMP/TMP under `C:/Temp/agentic-framework-migration/reviewer-r2`, disabled pytest caching, and set the simulated adopter's RECEIPTS_DIR to a distinct `reviewer-r2/simulated-adopter-receipts` child. This isolates fixture receipt semantics from the parent dispatch root without changing gates. The package-checking child alone used `AGENT_MODEL_REGISTRY=P:/.agent/model-registry.json` and `AGENT_MODEL_REGISTRY_HOME=P:/.agent`. Its real checker was available; the dispatch exception copy's unrelated missing checker is not a product defect.

The scratch driver saves each child's returncode, exact stdout/stderr bytes and full argv before interpreting results. Decisive observations are copied here so receipt deletion does not erase the evidence. Driver success does not relabel expected negative-child exits as zero.

```json
{
  "schema_version": "evidence.v1",
  "check_id": "review-r2-input-identity",
  "command": "rtk proxy C:/Python314/python.exe -B -X utf8 C:/Temp/agentic-framework-migration/reviewer-r2/check.py",
  "cwd": "P:/agentic-framework",
  "scope": "Independent current input identity",
  "phase": "targeted",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "sha256:13349cf2c9fa1afa3eff1c25ba21cd577b2bbf8bcbbc2625c171f709d2387b4c",
  "output": "INPUT sha256:13349cf2c9fa1afa3eff1c25ba21cd577b2bbf8bcbbc2625c171f709d2387b4c files=144 matches_documented=True. The identical hash held after focused tests, package verification and independent probes."
}
```

Reimplemented the documented algorithm independently: sort relative POSIX paths for all files in core/ and scripts/, excluding __pycache__ and .pytest_cache, plus the four named root adoption/checklist Markdown files; hash UTF-8 path, NUL, raw bytes, NUL. This matches the Corrections Applied evidence, including the producer's **36 tests / 36 subtests**, reference/packaging checks, task/closeout/ledger/adapter selftests and PowerShell encoding/parse results. Those full results were **reviewed and retained, not independently rerun in round 2**. The hash binds inputs, not the environment or the truth of every historical execution claim.

```json
{
  "schema_version": "evidence.v1",
  "check_id": "review-r2-focused-tests",
  "command": "rtk proxy C:\\Python314\\python.exe -B -X utf8 -m pytest core/tools/tests/test_review_output_pipeline.py scripts/tests/test_governance_migration.py::PackagingTests -q -p no:cacheprovider --basetemp C:\\Temp\\agentic-framework-migration\\reviewer-r2\\pytest-focused",
  "cwd": "P:/agentic-framework",
  "scope": "Changed output pipeline and packaging consumers",
  "phase": "targeted",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "sha256:13349cf2c9fa1afa3eff1c25ba21cd577b2bbf8bcbbc2625c171f709d2387b4c",
  "output": "17 passed, 8 subtests passed in 1.25s"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "review-r2-independent-consumers",
  "command": "rtk proxy C:/Python314/python.exe -B -X utf8 C:/Temp/agentic-framework-migration/reviewer-r2/probes.py",
  "cwd": "P:/agentic-framework",
  "scope": "Actual adaptation, normalization, schema CLI and read-only ledger loader",
  "phase": "targeted",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "sha256:13349cf2c9fa1afa3eff1c25ba21cd577b2bbf8bcbbc2625c171f709d2387b4c",
  "output": "PASS: 13 verdict cases; no-op, 3 schema failure cases, legacy mode; input unchanged. Each normalization exited 0; valid manual/command schema CLIs exited 0 and ledger loads accepted; all 11 malformed-verdict schema CLIs exited 1 and ledger loads refused. Missing/malformed/invalid schema normalization exited 3 without changing input. Exact CRLF/UTF-8 raw backups and unchanged no-op bytes asserted."
}
```

The probe first executed the real `adapt` CLI (exit 0) and validated both positive model-shaped fixtures against its generated schema. It then executed, per fixture, `rtk proxy C:\Python314\python.exe -B -X utf8 P:\agentic-framework\core\tools\adapt_output_schema.py strip-nulls <fixture.verdict.json> --schema P:\agentic-framework\core\.agent\schemas\review-verdict.schema.v2.json --raw-copy <fixture.raw.json>`, followed by the real `validate_json_schema.py <fixture.verdict.json> <original-schema>` CLI and the read-only `review_ledger.load_verdict` function. Paths and complete child commands are preserved in the scratch JSON receipts. No ledger operation was invoked.

| Fixture | Adapter exit | Schema CLI exit | Ledger loader | Decisive assertion |
|---|---:|---:|---|---|
| Valid manual | 0 | 0 | accepted | procedure/observer and exit_code:null survive; unused command:null removed |
| Valid command | 0 | 0 | accepted | command/exit_code:0 survive; unused procedure/observer nulls removed |
| Manual missing procedure, observer, or exit (3 cases) | 0 | 1 each | refused each | Invalid evidence does not become valid by normalization |
| Manual integer exit | 0 | 1 | refused | Manual requires null exit |
| Command missing/null/string/boolean exit (4 cases) | 0 | 1 each | refused each | Command requires an actual integer exit |
| Missing evidence | 0 | 1 | refused | `evidence` remains required |
| Required evidence:null | 0 | 1 | refused | Required null remains present and is rejected |
| Unknown unexpected:null | 0 | 1 | refused | Unknown null remains present; additional property rejected |

All 13 backups equaled the original CRLF/UTF-8 bytes, including the non-ASCII evidence. No-op normalization left input byte-identical. Schema-less mode retained legacy recursive null-key removal while preserving null array elements, zero and false. Missing, malformed JSON and schema-invalid original schemas each returned 3 and preserved input bytes.

Probe execution history: the first independent driver returned **1** after all 13 verdict cases passed because its `unchanged.json` receipt collided with its own no-op fixture name. This was a disposable harness defect: the receipt writer overwrote the fixture after the adapter returned. Fixture names were separated from receipt names only under reviewer-r2; rerunning the same assertions returned **0**. No product change or relaxed assertion was involved.

```json
{
  "schema_version": "evidence.v1",
  "check_id": "review-r2-package-verify",
  "command": "rtk proxy C:\\Python314\\python.exe -B -X utf8 scripts/sanitize.py --verify",
  "cwd": "P:/agentic-framework",
  "scope": "Actual shared-registry read-only package gate; protected pin remains an external release condition",
  "phase": "targeted",
  "result": "fail",
  "exit_code": 4,
  "tested_state": "sha256:13349cf2c9fa1afa3eff1c25ba21cd577b2bbf8bcbbc2625c171f709d2387b4c",
  "output": "mode: VERIFY (read-only); files scanned: 138; files changed: 0; replacements: 0; verify: OK (0 raw slugs remain); VERIFY FAILED: model-slug (tier-1): 1 hit at core/AGENTS.md:86 claude-fable-5-1; VERIFY FAILED: prose model name (tier-1): 1 hit at core/AGENTS.md:86 claude-fable-5; references: OK (0 dangling); tool commands: OK (every tools/ path shipped or classified)."
}
```

The full release gate **still fails**. The scoped packaging recheck passes because the corrected raw-source check is clean and the only failures are the preserved pin reported by both model checks. Approval does not waive that condition.

### Manual review and AC/checklist disposition

Manual procedure: traced original-schema resolution through generation adaptation, normalization and authoritative post-validation in both wrappers, and inspected the adapter, schema and new-test assertions against F1/F2/F3 and AC-1..AC-5. Observer: **external-astra-reviewer**; **exit_code: null**. PowerShell preserves `$canonicalSchema` separately from `$apiSchemaPath` (`:770`, `:939`, `:943`), passes it at `:1173`, then validates against it at `:1209`. Bash does the equivalent at `:583`, `:712`, `:731`, `:912`, `:936`. Failure remains subject to authoritative post-validation. This is source inspection plus real shared-consumer execution, not a nested provider dispatch or native-platform certification.

IR-5: all new pipeline test arms are strong at the exercised boundary: exact reconstructed objects/raw bytes, real adapter subprocesses, actual schema acceptance/refusal and ledger-loader refusal; the missing-schema negative asserts unchanged input. New packaging tests assert exact six-form conversions, case-insensitive detection, idempotence and paired ordinary-prose acceptance/raw-leak refusal with unchanged bytes. Packaging unit fixtures mock only orthogonal model/reference gates; the separate actual shared-registry sanitizer run checks that limitation. The no-op, CRLF/non-ASCII, invalid exits/evidence and schema-failure probes supply independent checks. Existing unrelated tests retain the round-1 assessment and hash-bound correction evidence.

| Contract/check | Current result | Basis |
|---|---|---|
| AC-1 | pass in migration scope | F2 fixed; ordinary prose accepted, genuine identity forms detected, raw leak refused read-only; actual raw scan clean, links/tools resolve |
| AC-2 | pass | Prior durable-evidence and shared-blocker evidence retained at matching current identity; F3 missing-exit gap now closed |
| AC-3 | pass | Prior semantic preservation audit and current rule ledger retained; corrections do not alter human/egress/profile/ledger controls |
| AC-4 | pass | F1 fixed through actual adapter/schema/ledger consumers; manual null is preserved; prior static/targeted/full evidence remains applicable |
| AC-5 local | pass within stated limits | Existing local adoption/wrapper evidence retained; both changed wrapper call sites pass original schema; no native-platform inference |
| IR-1/IR-4/IR-5/IR-6 and DR-1/DR-4/DR-5/DR-7/DR-8 | pass within recheck scope | Real changed consumers and meaningful negatives; actual exits distinguished from expected outcomes; fresh input identity matches; release limits explicit |
| Native Linux/macOS, live loader/provider certification, optional M4 hooks | n/a | Outside this scoped approval |

### Verdict and limits

**approved; intent_achieved: yes.** F1/F2/F3 are fixed and no material scoped blocker remains. Current JSON findings are empty; the historical findings remain above and are closed by this recheck table. No correction phase, ledger mutation, commit, push or publication was performed or authorized. The wrapper owns recording round 2; successful recording of this response is not claimed in advance.

Only this canonical report's current frontmatter and this appended section are changed in the repository. The protected model pin remains in the unchanged input hash; the working-context REVIEW-TEMPLATE is preserved. Native Linux/macOS, actual loader certification and optional M4 hooks remain outside scope. **This approval neither certifies release readiness nor authorizes publication.**

Final response-shape check: real normalization and schema CLI both exited 0; read-only ledger loading accepted the response and preserved the manual checklist exit_code:null without recovery.


## Orchestrator round 2 dispatch confirmation

The wrapper's final status independently confirms `gpt-6-astra`, `high`, child exit 0,
wrapper exit 0, `turn.completed`, successful schema post-validation and automatic ledger
recording. The manual checklist's `exit_code: null` survived the normal pipeline; no
manual verdict recovery was needed. The reviewer result remains **approved**, zero
findings, `intent_achieved: yes`.

Dispatch command: `rtk proxy pwsh -NoProfile -File C:/Temp/agentic-framework-migration/start_governance_review_r2.ps1`.
Preserved exit: **0**. Decisive output:

```text
OK: recorded round 2 verdict=approved agent='external-astra-reviewer' blocking=0 intent_achieved=yes usage=1,615,723
     loop may close: approved with no blocking findings.
```

Verification command: `rtk proxy python -X utf8 C:/Temp/agentic-framework-migration/verify_review_round.py 2`.
Preserved exit: **0**. Schema validation and ledger agreement passed; before/after
repository hashes found only this canonical report changed during the reviewer run.
The shared registry and resolver module hashes remained identical to their pre-dispatch
values. Round 1 and its 5,659,552 usage units remain in the same ledger; round 2 added
1,615,723. The intentional F3 schema change was acknowledged through the recorded
continue operation, which re-pinned the instrument and added one round without resetting
counts or increasing the token budget.

The continued same-vendor exception has reached its `approved` stop condition. No further
review dispatch is authorized by that exception. Scoped review approval does not remove
the protected pin or certify unmeasured release platforms/loaders. No commit or publication.
