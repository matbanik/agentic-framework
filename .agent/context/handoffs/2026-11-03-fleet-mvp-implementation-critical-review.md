---
date: "2026-11-04"
review_mode: "execution"
target_plan: "docs/execution/plans/2026-11-03-fleet-mvp/implementation-plan.md"
verdict: "approved"
findings_count: 2
template_version: "2.2"
requested_verbosity: "standard"
agent: "gpt-6.1-sol"
---

# Critical Review: 2026-11-03-fleet-mvp

> **Review Mode**: `execution`
> **Verdict**: `approved`

## Scope

**Target:** the explicitly named fleet MVP handoff, approved plan/task, six tracked diffs, fleet implementation/bootstrap/template, three test modules and harness, plan-local checkers and prepared scripts, local av-kit manifest, and supporting receipts. HEAD: `3a4eac6bfda70d0138939c6a37d8da7d0f771ce8` plus the uncommitted tree. One project handoff; the similarly dated fleet-handoff and proposal/research inputs are not deliverables under review.

**Checklist Applied:** IR-1 through IR-7 and DR-1 through DR-8, adapted to this stdlib CLI/HTTP service. No product changes; no live calls or machine changes. All synthetic repositories, hubs and member processes used C:/Temp. Synthetic fixture commits/refs were created only there by the requested tests/probes, never in either reviewed repository.

## Round 1 (2026-11-04)

**Intent anchor:** "SUPER can hand work to another machine on the LAN and get the result back, with the least machinery that does not need rebuilding later." The delivered LAN round trip achieves the core interaction; the two demonstrated secret-check defects leave the binding contract partially achieved.

## Findings

| # | Severity | Blocking | Kind | Finding | File:Line | Recommendation | Status |
|---|---|---|---|---|---|---|---|
| F-001 | High | yes | behavior | The secret-path check scans only the new snapshot tree, but the full bundle includes its HEAD parent and all reachable history. In a disposable repo, a tracked deploy.pem was removed from the index and ignored, alongside the ignored manifest. make_snapshot succeeded; deploy.pem was absent from the new tree but its synthetic private contents were recoverable from the bundle with git show <snapshot>^:deploy.pem. cmd_run uploads that bundle immediately. Thus another ignored secret file can leave SUPER despite AC-24 and the D-8 assertion that no other ignored file travels. Existing AC-23/24 tests examine only the tip tree and secrets never present in history. | `.agent/fleet/fleet.py:1062` | Apply the existing secret-path patterns and allowlist to every path whose contents the full bundle will carry, including ancestor trees, before upload. Add a regression with a staged-deleted, now-ignored deploy.pem and assert refusal before any blob or task is created. Preserve the approved snapshot ancestry and full-bundle design. | fixed |
| F-002 | High | yes | behavior | validate_envelope scans body, refs and start_quote only. The freely accepted created and reply_to strings bypass the same secret-value patterns. Against an isolated real TLS hub, placing a synthetic ghp_-pattern value in either field returned HTTP 200, added a task row, and persisted the value in the append-only messages table. test_ac12_secret_values_are_refused parametrizes only the three scanned fields, so it stays green. This violates the binding no-secret-in-a-message rule and AC-12. | `.agent/fleet/fleet.py:187` | Run the existing secret-value check over the complete accepted envelope, and extend the HTTP negative tests to the other string fields for both submitted tasks and status messages. Assert secret_in_message, zero added rows and absence from database bytes. | fixed |
| F-003 | Medium | no | behavior | run_steps discards taskkill /T /F failure diagnostics and kills only the immediate process afterward. The reviewer targeted run was 272 passed, 1 failed, and an isolated repeat failed the same AC-29 sentinel assertion. Instrumentation observed taskkill exit 1 with ERROR: Access denied under CodexSandboxOffline; the descendant survived. The original unrestricted 273-pass and 4317-pass receipts are authentic. This is an observed restricted-account limitation, not evidence that DUPER fails the timeout contract, so it does not block this loop. | `.agent/fleet/fleet.py:1281` | Expose and handle process-tree termination failure so operators are told that descendants may survive. Preserve the restricted-account reproduction and confirm timeout cleanup in the supported member environment; no sandbox or process-isolation redesign is requested. | accepted_risk |

F-001 violates **AC-24** (and qualifies AC-23/D-8’s ignored-file claim). F-002 violates **AC-12** and the explicit no-secret-in-message constraint. Both are high-confidence deliverable behavior findings. They do not fit any closed-vocabulary mechanism, so neither is classified as `control-defeat`. F-003 is high-confidence about this restricted account only; it is non-blocking.

## Checklist Results

### Acceptance-criteria audit

Each row below reflects code inspection plus the named targeted tests, not merely the test name or a checked handoff cell.

| AC | Result | Code and test observation |
|---|---|---|
| AC-1 | pass | validate_envelope checks shape/types/closed kind; missing-field and wrong-shape cases are real. |
| AC-2 | pass | Closed TRANSITIONS; total pair walk and terminal refusal, backed by actual task transitions. |
| AC-3 | pass | SQLite BEFORE UPDATE/DELETE triggers and BEGIN IMMEDIATE rollback; real full-task test preserves prior rows byte-for-byte. |
| AC-4 | pass | AST stdlib/3.11 and source rules pass; fleet home derives from Path.home(). No prohibited environment-variable mutation in fleet.py. |
| AC-5 | pass | hub_request compares the DER pin at 952 before constructing Authorization at 956 or request at 965. Wrong-pin byte-count tests and deliberately wrong-order oracle pass. |
| AC-6 | pass | Known non-open routes authenticate. Member digest only; pending/revoked refused; fake raw key absent from real test database/WAL. |
| AC-7 | pass | Pair name/digest validation, pending bound and collision check inside transaction. Approval/revocation local only and real-console guarded; no approving HTTP endpoint. |
| AC-8 | pass | SEND_POLICY checks authenticated identity before task append. Every member task kind refused; landing kinds unknown, agent disabled. D-4 trusted execution stays accepted. |
| AC-9 | pass | Real TLS hub/member ping returns versions and online state; offline wait exits 5. |
| AC-10 | pass | Claim/session touch/working append share one BEGIN IMMEDIATE; 8 concurrent requests produce one working row and one recoverable task. |
| AC-11 | pass | Owner/session/transition/duplicate-content checks occur within the same write transaction; repeated id returns already_recorded without append. |
| AC-12 | fail | Existing tests strongly assert the three scanned fields, but complete messages still accept secret values in created/reply_to. F-002. |
| AC-13 | pass | Store and TLS files persist; member_call retries hub_unreachable with stable status id. Offline queue, hub restart, lost connectivity result and wait exits covered. |
| AC-14 | pass | New hello atomically replaces session and fails working tasks. Old idle member exits 2. Mid-run restart tested; stated Windows orphan-process limitation accepted. |
| AC-15 | pass | TLS handshake occurs per connection in handler thread with timeout; oversized JSON refused; raw non-handshaking connections do not stop ping. |
| AC-16 | pass | Tests traverse closed route table without key and orchestrator-only routes with member key; dispatch authenticates before handler. |
| AC-17 | pass | Fixed bootstrap byte dictionary; source/served/printed hashes match; traversal and key paths return 404. |
| AC-18 | pass | Publish validates and appends; latest manifest wins. check reports actual missing tools and does not open a new member session. |
| AC-19 | pass | All five stop markers, required headings, empty Linux/macOS sections, key-read prohibition, update hash instruction present. |
| AC-20 | pass (receipts) | Saved before rule absent; after exactly one enabled LAN-scoped Private TCP8770 rule; profiles unchanged, Plex Any-allow and SMB enabled. Pure predicates re-evaluated; no live firewall call. |
| AC-21 | pass (receipts) | Saved DUPER online/approved versions and ping completion; before/after log-collector/profiles/inbound counts unchanged and keyless probe 401. No WinRM used by reviewer. |
| AC-22 | pass | Manifest version strict int, closed keys/names/argv/requires; forbidden first-argument basename forms tested. Trusted project code remains unrestricted under D-4. |
| AC-23 | partial | Temporary copied index, explicit GIT_INDEX_FILE, unsigned dangling snapshot, finally-deleted ref. Dirty fixture before/after hashes/index/HEAD/branches/worktrees match. D-8 force-add is exact in the tip tree, but ancestor payload is not screened: F-001. |
| AC-24 | fail | Current-tree path check blocks the listed current secret paths before upload. A staged-deleted now-ignored deploy.pem still travels through the full bundle parent: F-001. |
| AC-25 | pass | Real end-to-end marker/log hash/tree/exit/status round trip. First failing argv stops later sentinel step. Log tail separately checked. |
| AC-26 | pass | Slot prepared and manifest/all argv tools resolved before any step; rejection states/reasons and sentinel absence asserted across malformed/unknown/corrupt/forbidden cases. |
| AC-27 | pass | Hash-addressed PUT verifies content and replaces atomically; bounds, absent bundle and per-task member download ownership checked. Blob contents are not globally secret-scanned by design. |
| AC-28 | pass | Slot uses init/fetch and detached checkout, no origin or heads. clean removes stale untracked file and preserves ignored deps. Slot commit remains absent from later snapshot history and never lands on SUPER. |
| AC-29 | partial | Heartbeat test passes. Timeout sentinel fails under reviewer account because taskkill gets Access denied; original unrestricted test receipt passes. F-003 records the limitation without asserting a live DUPER failure. |
| AC-30 | pass | Popen inherits member environment; no fleet edits to billing/entrypoint variables. Child prints both sentinel and CLAUDECODE unchanged. |
| AC-31 | pass (receipts) | Local manifest matches registered named commands. setup exits 0; check-py/ui/mcp exit 1 with matching logs/trees. Current av-kit refs/fleet empty and branch/worktree lists match original before record. Builds never reached, correctly disclosed. |
| AC-32 | pass (recorded full) | Manifest entries exist; package comparison and selftests pass. Historical full: 4317 passed, 1 skipped, 36 subtests passed, matching receipt and independent configured state. Targeted environmental exception above is not presented as a fresh full green. |

### IR / DR results

| Checklist | Result | Observation |
|---|---|---|
| IR-1, IR-2 | pass / n/a | Real TLS subprocess round trips; no behavior-substituting stubs in the integration route. |
| IR-3, IR-6 | partial | Closed refusal codes and route/shape checks are real; F-002 demonstrates incomplete envelope secrecy validation. Web-API-specific NotFoundError mapping is n/a. |
| IR-4 | pass | D-6 closes direct/transitive removed-fixture imports; the moved test retains its assertions. |
| IR-5 | partial | Per-test inventory below. Assertions are substantive; AC-12 and AC-24 miss material input classes (F-001/F-002). Timeout test correctly detects an environmental failure. |
| IR-7 | pass | All 32 ACs present; integration rows have real tests or live receipts; no disguised deferred implementation. H2 remains pending as expected. |
| DR-1, DR-4, DR-8 | partial | Receipt claims are supported and limitations stated. Broader secret guarantees exceed demonstrated behavior. |
| DR-2, DR-3, DR-6 | pass | Changed paths, manifest and commands agree; no behavior-affecting stale reference found in scope. |
| DR-5, DR-7 | pass | All 19 cited receipt hashes match; observed outputs support the handoff. Prior green and current restricted failure kept distinct. |

### Commands and decisive observations

Test commands ran with `PYTHONDONTWRITEBYTECODE=1`, `RECEIPTS_DIR=C:/Temp/agentic-framework/receipts`, `AGENT_MODEL_REGISTRY_HOME=P:/.agent`; pytest used `-p no:cacheprovider` and explicit C:/Temp basetemp. These environment values were assigned in PowerShell before the recorded Python invocations.

```json
{
  "schema_version": "evidence.v1",
  "check_id": "exec-r1-1",
  "cwd": "P:/agentic-framework",
  "scope": "Targeted fleet suite, AC-1..19 and AC-22..30",
  "phase": "targeted",
  "result": "fail",
  "exit_code": 1,
  "tested_state": "9e1ccecb4ffc4ec5ca7667590c9c2f08d693d2e948d921a8db4588cbe1dfb7ea",
  "command": "rtk proxy python -m pytest scripts/tests/test_fleet_hub.py scripts/tests/test_fleet_bootstrap.py scripts/tests/test_fleet_run.py -q -rfE -p no:cacheprovider --basetemp C:/Temp/agentic-framework/receipts/dispatch/fleet-mvp-exec-r1/pytest-temp",
  "output": "272 passed, 1 failed in 153.40s; only test_ac29_a_timeout_kills_the_whole_tree failed. Isolated repeat: 1 failed in 11.50s. taskkill returned Access denied in the restricted reviewer account; F-003."
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "exec-r1-2",
  "cwd": "P:/agentic-framework",
  "scope": "Adversarial full-bundle secret-path probe",
  "phase": "targeted",
  "result": "fail",
  "exit_code": 0,
  "tested_state": "9e1ccecb4ffc4ec5ca7667590c9c2f08d693d2e948d921a8db4588cbe1dfb7ea",
  "command": "rtk proxy python C:/Temp/agentic-framework/receipts/dispatch/fleet-mvp-exec-r1/reviewer_probes.py history",
  "output": "Probe completed: ignored deploy.pem absent from snapshot tip, snapshot accepted, ancestor_secret_recoverable=true, source refs/fleet empty. Exit 0 means the diagnostic ran, not that AC-24 passed; F-001."
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "exec-r1-3",
  "cwd": "P:/agentic-framework",
  "scope": "Adversarial whole-envelope secret-value probe",
  "phase": "targeted",
  "result": "fail",
  "exit_code": 0,
  "tested_state": "9e1ccecb4ffc4ec5ca7667590c9c2f08d693d2e948d921a8db4588cbe1dfb7ea",
  "command": "rtk proxy python C:/Temp/agentic-framework/receipts/dispatch/fleet-mvp-exec-r1/reviewer_probes.py message",
  "output": "Both created and reply_to: HTTP 200, new_rows=1, fake_secret_persisted=true. Exit 0 means the diagnostic ran; F-002."
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "exec-r1-4",
  "cwd": "P:/agentic-framework",
  "scope": "D-6 portable installation and moved-test regression",
  "phase": "targeted",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "9e1ccecb4ffc4ec5ca7667590c9c2f08d693d2e948d921a8db4588cbe1dfb7ea",
  "command": "rtk proxy python -m pytest scripts/tests/test_instantiate_credits_nonwin.py core/tools/tests/test_lane_route_instructions.py core/tools/tests/test_credits_phases.py::test_credits_docs_name_the_identity_create -q -rfE -p no:cacheprovider --basetemp C:/Temp/agentic-framework/receipts/dispatch/fleet-mvp-exec-r1/d6-temp",
  "output": "38 passed, 37 warnings in 6.02s. All 17 added module exclusions depend directly or transitively on removed fixtures; moved assertions preserved."
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "exec-r1-5",
  "cwd": "P:/agentic-framework",
  "scope": "AC-32 package comparison",
  "phase": "targeted",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "9e1ccecb4ffc4ec5ca7667590c9c2f08d693d2e948d921a8db4588cbe1dfb7ea",
  "command": "rtk proxy python docs/execution/plans/2026-11-03-fleet-mvp/check_package_gates.py",
  "output": "0 problem(s) against baseline head 3a4eac6. Separate --selftest exited 0 and detected a removed baseline failure line."
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "exec-r1-6",
  "cwd": "P:/agentic-framework",
  "scope": "Live-check falsification cases",
  "phase": "targeted",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "9e1ccecb4ffc4ec5ca7667590c9c2f08d693d2e948d921a8db4588cbe1dfb7ea",
  "command": "rtk proxy python docs/execution/plans/2026-11-03-fleet-mvp/check_live.py --selftest",
  "output": "selftest ok: 5 good samples, 26 bad samples; no live mode was executed."
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "exec-r1-7",
  "cwd": "P:/agentic-framework",
  "scope": "Receipt integrity, independently computed identity and live-record audit",
  "phase": "targeted",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "9e1ccecb4ffc4ec5ca7667590c9c2f08d693d2e948d921a8db4588cbe1dfb7ea",
  "command": "rtk proxy python C:/Temp/agentic-framework/receipts/dispatch/fleet-mvp-exec-r1/reviewer_audit.py",
  "output": "All 19 evidence.v1 receipt hashes matched. Independently computed configured identity 9e1ccecb4ffc4ec5ca7667590c9c2f08d693d2e948d921a8db4588cbe1dfb7ea. Saved firewall, DUPER and av-kit records satisfy their pure predicates; current av-kit branches/worktrees match before record and refs/fleet is empty. Historical full receipt: 4317 passed, 1 skipped, 36 subtests passed. No live hub or member was contacted."
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "exec-r1-8",
  "cwd": "P:/agentic-framework",
  "scope": "Fresh full evidence validation",
  "phase": "targeted",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "9e1ccecb4ffc4ec5ca7667590c9c2f08d693d2e948d921a8db4588cbe1dfb7ea",
  "command": "rtk proxy python core/tools/durable_evidence.py .agent/context/handoffs/2026-11-03-fleet-mvp-handoff.md --require-full --expected-state 9e1ccecb4ffc4ec5ca7667590c9c2f08d693d2e948d921a8db4588cbe1dfb7ea",
  "output": "OK: durable evidence records. Full receipt SHA-256 7b3b7cfb9906b0b20b7a5c2e69e09131970258c834f47478fae1d7fdeaade2b3 matched. Reviewed code/test input timestamps precede the full run; path-based identity limitations are disclosed. Full suite was not repeated."
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "exec-r1-9",
  "cwd": "P:/agentic-framework",
  "scope": "Task and handoff AC coverage",
  "phase": "targeted",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "9e1ccecb4ffc4ec5ca7667590c9c2f08d693d2e948d921a8db4588cbe1dfb7ea",
  "command": "rtk proxy python core/tools/validate_closeout_artifacts.py --plan docs/execution/plans/2026-11-03-fleet-mvp/implementation-plan.md --handoff .agent/context/handoffs/2026-11-03-fleet-mvp-handoff.md --ac-coverage-only",
  "output": "OK: all 32 plan AC(s) present in the handoff. Separate task lint exited 0: 39 rows; dependencies resolve and are acyclic."
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "exec-r1-10",
  "cwd": "P:/agentic-framework",
  "scope": "IR-1..7 and DR-1..8 source audit",
  "phase": "manual",
  "result": "fail",
  "exit_code": null,
  "tested_state": "9e1ccecb4ffc4ec5ca7667590c9c2f08d693d2e948d921a8db4588cbe1dfb7ea",
  "command": null,
  "output": "Runtime round trips and refusal tests are substantive. Transactions cover claim, status and pair. Pin precedes key headers. No member work-submission or landing route found within D-4. AC-12 and AC-24 have demonstrated counterexamples; restricted timeout failure recorded separately. No missing or unsupported handoff receipt claim found.",
  "procedure": "Read the complete fleet implementation, bootstrap, manifest, three fleet test modules, harness, local checkers and prepared scripts; compare six tracked diffs, D-6 moved assertions, all AC rows, and raw receipts. Trace every HTTP route through dispatch/authentication/role policy and each CLI/member executor. Audit assertion strength per test in the markdown inventory.",
  "observer": "gpt-6.1-sol"
}
```

### Rulings on every handoff reviewer point

| Point | Ruling |
|---|---|
| 1: D-5..D-9 execution amendments | Reviewed here, using the supplied verbatim human decisions as authorization. |
| 2: delayed live refresh, D-9 | Accepted. Pre-D-8 hash 644262a9988c0ebf is recorded consistently; SUPER made D-8 snapshots locally. Refresh once after corrections/review settle the file. No stale-version defect. |
| 3: D-8 before its ruling | Sequence departure acknowledged; subsequent explicit acceptance settles the delivered behavior. No new decision requested. Its exact-path tip-tree addition is sound; F-001 concerns unexamined ancestor payload. |
| 4: D-6 coverage cost | Accurate: 17 additional modules (152 test functions before parametrization) removed from non-Windows installs. Their direct/transitive fixture dependency is real; portable retained-test collection passes. The moved identity test now belongs to the already Windows-only credits file and preserves its assertions. No extra removal requested. |
| 5: pair over WinRM | Accepted under D-5. Key created on DUPER, only digest/approval code leaves it, approval still requires Mat in a terminal. No live credentials opened. |
| 6: pairing.txt, capabilities column, ACTION= interface | Accepted as small implementation details. Pairing file contains public trust/bootstrap values, not keys. Capability state is mutable operational state. ACTION includes a named-task Remove operation; no autostart trigger. |
| 7: full-gate identity | Independently matches 9e1ccecb.... All 19 receipt hashes match. Reviewed code/test timestamps precede full start (latest input 14:56:16 UTC; full starts about 14:59:28, ends 15:38:46). Path identity does not prove content retrospectively; the handoff explicitly discloses that limit and the observed mtime evidence supports this run. No repeat 40-minute run solely for bookkeeping. Corrections invalidate affected/full evidence normally. |
| 8: av-kit -x / step stopping | Accurate. Python stops after 404 passes + 1 failure; UI 1111 passes + 4 failures; MCP 450 passes + 16 failures. Both builds are after failing test steps and did not run. AC-31 permits reporting those failures without fixing av-kit. |

**D-5 discipline:** Read the local network notes (lines 145-149) and all prepared scripts. The plan sequences a before record, named reversible LAN-only rule, and after checks for profiles, Plex and SMB. The existing rule is not replaced and no profile is enabled. DUPER records preserve log-collector/profiles/inbound counts; setup opens no member port and adds no GitHub login/signing key. The triggerless Fleet member task has explicit Stop/Remove; application installs are per-user. No router changes were made by these scripts. The existing requirement to dump router filter state before a network change remains a procedural prerequisite; this review does not infer a router mutation or add a new network controller.

**D-7:** Keep the excluded local av-kit manifest until a separately authorized commit. It was neither committed nor removed by this reviewer. No branch or worktree created on SUPER.

**Authority boundary:** All known work creation runs through authenticated SEND_POLICY; members cannot create tasks through task/status/project routes. No commit/push/merge/tag/release/plan-transition endpoint exists. Project subprocesses can call tools/network under D-4; that approved trust boundary is accepted. Absence of member GitHub credentials/signing keys is a setup fact and was not re-audited on the live member, per this dispatch’s limits. No sandbox requested.

### IR-5 individual test inventory

Ratings apply to each named function and all its parameter instances. Strong means concrete observable result/refusal/persistence assertions; Adequate means a narrower structural or success-only assertion backed by other behavior tests. No trivially passing Weak test found. Missing input classes remain F-001/F-002, even though existing individual assertions are strong.

#### test_fleet_hub.py (57 functions)

| Test | Rating |
|---|---|
| `test_ac01_accepts_a_complete_envelope` (line 48) | Strong |
| `test_ac01_refuses_an_extra_field` (line 52) | Strong |
| `test_ac01_refuses_a_wrong_version` (line 56) | Strong |
| `test_ac01_refuses_each_missing_field` (line 61) | Strong |
| `test_ac01_refuses_wrong_types` (line 80) | Strong |
| `test_ac01_refuses_a_non_object` (line 84) | Strong |
| `test_ac02_transitions_are_total_over_states` (line 91) | Adequate |
| `test_ac02_terminal_states_have_no_exit` (line 96) | Strong |
| `test_ac02_unknown_state_fails_closed` (line 101) | Strong |
| `test_ac03_update_and_delete_abort_with_append_only` (line 117) | Strong |
| `test_ac03_append_adds_exactly_one_row_and_changes_none` (line 129) | Strong |
| `test_ac03_tx_rolls_back_on_error` (line 140) | Strong |
| `test_ac04_source_rules_hold` (line 175) | Adequate |
| `test_ac04_checker_can_fail` (line 180) | Strong |
| `test_ac05_wrong_pin_stops_status_before_any_byte` (line 239) | Strong |
| `test_ac05_wrong_pin_stops_pair_before_any_byte` (line 254) | Strong |
| `test_ac05_oracle_a_client_that_writes_first_is_seen` (line 268) | Strong |
| `test_ac06_no_key_and_wrong_key_are_unauthorized` (line 282) | Strong |
| `test_ac06_pending_member_is_not_approved` (line 288) | Strong |
| `test_ac06_revoked_member_is_revoked` (line 294) | Strong |
| `test_ac06_raw_key_is_not_in_the_database` (line 304) | Strong |
| `test_ac07_approve_needs_a_tty_and_adds_no_row` (line 314) | Strong |
| `test_ac07_approve_refuses_piped_stdin` (line 323) | Strong |
| `test_ac07_revoke_needs_a_tty_too` (line 339) | Strong |
| `test_ac07_wrong_code_is_refused_and_adds_no_row` (line 348) | Strong |
| `test_ac07_right_code_approves` (line 357) | Strong |
| `test_ac07_no_http_route_approves` (line 364) | Adequate |
| `test_ac07_reused_name_is_taken_until_revoked` (line 373) | Strong |
| `test_ac07_bad_names_are_refused` (line 386) | Strong |
| `test_ac07_pair_validates_its_fields` (line 393) | Adequate |
| `test_ac07_pending_is_limited` (line 398) | Strong |
| `test_ac07_pair_never_prints_the_key` (line 405) | Strong |
| `test_ac08_members_cannot_send_tasks` (line 420) | Strong |
| `test_ac08_agent_kind_is_not_enabled` (line 429) | Strong |
| `test_ac08_landing_kinds_do_not_exist` (line 438) | Strong |
| `test_ac08_from_must_match_the_key` (line 446) | Strong |
| `test_ac08_task_needs_an_approved_member` (line 455) | Strong |
| `test_ac08_executors_match_the_send_policy` (line 466) | Adequate |
| `test_ac12_secret_values_are_refused` (line 475) | Strong |
| `test_ac15_raw_client_does_not_stop_requests` (line 489) | Strong |
| `test_ac15_oversized_json_is_refused` (line 499) | Strong |
| `test_ac03_full_task_leaves_earlier_rows_unchanged` (line 563) | Strong |
| `test_ac09_ping_round_trip_with_real_processes` (line 584) | Strong |
| `test_ac09_stopped_member_makes_wait_exit_5` (line 600) | Strong |
| `test_ac10_concurrent_claims_give_one_working_row` (line 620) | Strong |
| `test_ac10_repeat_next_returns_the_same_task_and_adds_no_row` (line 635) | Strong |
| `test_ac10_next_with_no_task_is_null` (line 644) | Strong |
| `test_ac11_status_posts_are_owner_transition_and_id_checked` (line 651) | Strong |
| `test_ac11_status_needs_a_string_state_and_a_status_kind` (line 677) | Strong |
| `test_ac13_task_sent_while_off_reaches_the_member_on_start` (line 692) | Strong |
| `test_ac13_hub_restart_keeps_pin_and_tasks` (line 699) | Strong |
| `test_ac13_result_lands_across_a_hub_restart` (line 709) | Strong |
| `test_ac13_busy_member_makes_wait_exit_4` (line 724) | Strong |
| `test_ac13_hub_down_makes_status_exit_2` (line 734) | Strong |
| `test_ac14_restart_fails_the_members_working_task` (line 744) | Strong |
| `test_ac14_second_process_makes_the_first_exit_2` (line 754) | Strong |
| `test_ac15_raw_client_does_not_stop_a_concurrent_ping` (line 767) | Strong |

#### test_fleet_bootstrap.py (21 functions)

| Test | Rating |
|---|---|
| `test_ac16_open_routes_are_real_routes` (line 53) | Adequate |
| `test_ac16_every_other_route_needs_a_key` (line 58) | Strong |
| `test_ac16_open_routes_work_with_no_key` (line 64) | Strong |
| `test_ac16_a_member_cannot_call_orchestrator_routes` (line 71) | Strong |
| `test_ac17_served_files_match_the_pairing_line` (line 84) | Strong |
| `test_ac17_the_hub_saves_the_pairing_line` (line 95) | Strong |
| `test_ac17_other_bootstrap_paths_are_not_found` (line 112) | Strong |
| `test_ac18_publish_then_check_lists_missing_tools` (line 123) | Strong |
| `test_ac18_check_passes_when_nothing_is_missing` (line 138) | Strong |
| `test_ac18_check_with_no_project_needs_no_hub` (line 146) | Strong |
| `test_ac18_check_on_the_hub_machine_uses_the_orchestrator_key` (line 154) | Strong |
| `test_ac18_check_does_not_end_a_running_members_session` (line 160) | Strong |
| `test_ac18_latest_publish_wins` (line 168) | Strong |
| `test_ac18_unknown_project_is_not_found` (line 179) | Strong |
| `test_ac18_invalid_manifest_is_refused_with_no_row` (line 196) | Strong |
| `test_ac18_a_manifest_holding_a_secret_value_is_refused` (line 203) | Strong |
| `test_ac18_publish_refusals_exit_2_before_any_row` (line 212) | Strong |
| `test_ac19_the_template_has_its_shape` (line 259) | Strong |
| `test_ac19_the_checker_sees_a_removed_stop_line` (line 264) | Strong |
| `test_ac19_the_checker_sees_the_other_breaks` (line 269) | Strong |
| `test_ac19_the_template_names_the_firewall_rule_and_the_update_steps` (line 278) | Adequate |

#### test_fleet_run.py (47 functions)

| Test | Rating |
|---|---|
| `test_ac22_the_filled_template_is_valid` (line 33) | Strong |
| `test_ac22_the_unfilled_template_is_refused` (line 37) | Strong |
| `test_ac22_a_good_manifest_is_accepted` (line 41) | Strong |
| `test_ac22_bad_shapes_are_refused` (line 69) | Strong |
| `test_ac22_a_manifest_must_be_an_object` (line 74) | Strong |
| `test_ac22_forbidden_tools_are_refused_in_every_form` (line 80) | Strong |
| `test_ac22_a_forbidden_word_as_a_later_argument_is_not_refused` (line 86) | Strong |
| `test_ac23_the_bundle_has_the_working_tree_and_not_the_ignored_file` (line 225) | Strong |
| `test_ac23_an_ignored_manifest_still_travels_and_nothing_else_ignored_does` (line 242) | Strong |
| `test_ac23_the_commit_has_head_as_its_parent_and_is_unsigned` (line 254) | Strong |
| `test_ac23_the_repo_is_unchanged` (line 262) | Strong |
| `test_ac23_oracle_the_comparison_catches_a_clobbered_file` (line 270) | Strong |
| `test_ac23_a_failed_bundle_leaves_no_fleet_ref` (line 278) | Strong |
| `test_ac23_a_repo_with_no_head_is_refused` (line 293) | Strong |
| `test_ac23_run_refuses_a_missing_or_bad_manifest` (line 303) | Strong |
| `test_ac23_an_oversized_snapshot_is_refused` (line 316) | Strong |
| `test_ac24_a_likely_secret_stops_the_run` (line 328) | Strong |
| `test_ac24_an_ignored_secret_and_the_allowed_names_pass` (line 339) | Adequate |
| `test_ac25_a_command_sees_uncommitted_files_and_its_log_comes_back` (line 351) | Strong |
| `test_ac25_a_nonzero_exit_fails_and_stops_at_that_argv` (line 368) | Strong |
| `test_ac25_a_long_log_keeps_its_tail` (line 386) | Strong |
| `test_ac14_a_member_killed_during_a_run_reports_member_restarted` (line 393) | Strong |
| `test_ac26_an_unknown_command` (line 419) | Strong |
| `test_ac26_a_snapshot_with_no_manifest` (line 427) | Strong |
| `test_ac26_a_bad_manifest_in_the_snapshot` (line 433) | Strong |
| `test_ac26_a_wrong_tree` (line 441) | Strong |
| `test_ac26_a_corrupt_bundle` (line 450) | Strong |
| `test_ac26_a_project_that_differs_from_the_slots_manifest` (line 459) | Strong |
| `test_ac26_an_absent_tool_runs_no_step` (line 468) | Strong |
| `test_ac26_a_forbidden_tool_in_a_directly_posted_task_never_runs` (line 477) | Strong |
| `test_ac26_oracle_the_gh_shim_records_a_call` (line 485) | Strong |
| `test_ac27_a_blob_round_trip` (line 505) | Strong |
| `test_ac27_content_that_does_not_match_the_hash` (line 515) | Strong |
| `test_ac27_an_oversized_blob` (line 521) | Strong |
| `test_ac27_a_task_naming_an_absent_bundle` (line 537) | Strong |
| `test_ac27_a_run_task_with_a_bad_shape` (line 561) | Strong |
| `test_ac27_a_member_reads_only_blobs_tied_to_its_tasks` (line 575) | Strong |
| `test_ac27_a_member_may_upload_a_blob` (line 588) | Adequate |
| `test_ac27_blob_routes_need_a_key` (line 595) | Strong |
| `test_ac27_a_non_hex_path` (line 603) | Strong |
| `test_ac27_an_absent_blob_is_not_found_for_the_orchestrator` (line 609) | Strong |
| `test_ac28_a_slot_has_no_remote_or_branch_and_is_cleaned` (line 629) | Strong |
| `test_ac28_a_commit_made_in_the_slot_stays_there_and_is_dropped` (line 653) | Strong |
| `test_ac29_a_timeout_kills_the_whole_tree` (line 686) | Strong |
| `test_ac29_oracle_the_child_writes_its_sentinel_when_not_killed` (line 702) | Strong |
| `test_ac29_a_member_stays_online_during_a_long_run` (line 709) | Strong |
| `test_ac30_the_environment_reaches_the_child_unchanged` (line 738) | Adequate |

`test_credits_docs_name_the_identity_create` in test_credits_phases.py: Strong for its documentation contract; source move preserves both positive locations and negative obsolete wording. The unchanged non-Windows regression module’s four tests are Strong (real temporary installation, retained dependency scan, and actual pytest collection). Unchanged unrelated credits-phase tests are outside this change’s assertion audit.

## Verdict

`changes_required` — fix F-001 and F-002 through the corrections workflow, then rerun affected tests and the required fresh full gate. Record/handle the restricted timeout observation without claiming a live DUPER failure. Perform the D-9 refresh only after the file settles, on the already authorized sequence. No corrections, live actions, repository commits or pushes were performed during this review.

The core LAN handoff/result path is implemented with suitable MVP machinery. Approval is blocked by the two reproduced secret-contract failures, not the accepted trust boundary, delayed deployment refresh, pre-existing package-gate failures, or av-kit’s own failures.

🕐 Completed: 2026-11-04 10:51 (EST)

## Corrections Applied (2026-11-04)

The implementing agent wrote this section. It is not a review verdict; round 2 decides.

| Finding | Verified against the code | Change | Regression |
|---------|---------------------------|--------|------------|
| F-001 | Yes: the check read only `ls-tree` of the new tree | `.agent/fleet/fleet.py`: new `bundle_paths`, used by `make_snapshot` in place of `ls-tree` | `scripts/tests/test_fleet_run.py`: 7 new AC-24 tests, 2 of them against over-refusal |
| F-002 | Yes: `has_secret` got three fields | `.agent/fleet/fleet.py`: `validate_envelope` scans the whole envelope; `validate_hello` scans capability versions | `scripts/tests/test_fleet_hub.py`: 4 new AC-12 test functions |
| F-003 | Partly: the discarded diagnostics are in the code; the Access denied result was not reproduced here | `.agent/fleet/fleet.py`: new `kill_tree` logs a failed `taskkill`; the reason stays `timeout` | `scripts/tests/test_fleet_run.py`: 2 new AC-29 tests |

**Census.** `hello`'s capability versions had the same gap as F-002 and are fixed. `pair` takes only a
checked name and a hex digest. The manifest route already scanned the whole manifest. Blobs stay
AC-12's stated limitation. `make_snapshot` is the only route that creates a bundle.

**Tests.** Red first: 21 failed, 37 passed. Fleet modules after the fixes: 311 passed. Full gate:
4355 passed, 1 skipped. Package gates: 0 problems against the baseline. `.env` deep in the history was
added after F-001's fix, so it has no red receipt.

**Not done.** F-003 on the real member, until the D-9 refresh. No plan or task file changed in this
pass, apart from row state. Details and receipts are in the handoff's Corrections Applied.

## Recheck (2026-11-04) — Round 2

**Intent anchor:** "SUPER can hand work to another machine on the LAN and get the result back, with the least machinery that does not need rebuilding later." **Intent achieved: yes. Verdict: approved.**

The original review and implementer's Corrections Applied section are retained above. The original Findings table's status cells now record this recheck's disposition; its round 1 descriptions and evidence remain historical. This is round 2 of 6, reviewed by `gpt-6.1-sol`, against HEAD `3a4eac6bfda70d0138939c6a37d8da7d0f771ce8` plus the uncommitted tree.

### Findings and disposition

| # | Severity | Blocking | Kind | Finding | File:Line | Recommendation | Status |
|---|---|---|---|---|---|---|---|
| F-001 | High | no | behavior | Fixed: the same path patterns and allowlist now cover reachable history, before update-ref or bundle creation. Current-tree refusals, original parent, ignored-manifest exception, repo preservation and failure cleanup pass. | `.agent/fleet/fleet.py:1046`, `:1071` | None for this correction. | fixed |
| F-002 | High | no | behavior | Fixed: both task and status routes validate and scan the complete envelope before persistence. Capability versions in hello are now scanned before session, timestamp, capability or restart-status writes. | `.agent/fleet/fleet.py:187`, `:451`, `:544`, `:588` | None for this correction. | fixed |
| F-003 | Medium | no | behavior | The diagnostic correction is verified. This restricted reviewer account still gets taskkill exit 1 / Access denied and a surviving descendant. New observation: the clean-kill/no-warning test also fails for that same denial, while the actual uploaded timeout log now truthfully warns that child processes may survive. The unrestricted 311-pass and fresh full receipts are authentic. Supported-member confirmation remains at the already ruled D-9 refresh. | `.agent/fleet/fleet.py:1281`; `scripts/tests/test_fleet_run.py:782`, `:820` | Carry out the already planned D-9 timeout check after refresh. No process isolation redesign requested. | accepted_risk |
| F-004 | Medium | no | behavior | A safe depth-1 source can produce a bundle that an empty recipient cannot fetch: Git reports missing parent / did not send all necessary objects; prepare_slot maps this to bundle_bad. Reproduced also with the pre-correction tip-tree scan. This is a shallow-source compatibility limitation, not a secret-path bypass or a correction regression. Full local history is the exercised MVP source case, including the two named repositories; no registered shallow-source success case is being withheld. | `.agent/fleet/fleet.py:1077`, `:1255` | State that source repositories need full local history; optionally refuse shallow sources before upload. No history reconstruction machinery is needed. | open |

No blocking finding remains. F-003 and F-004 concern deliverable behavior and do not fit a closed-vocabulary control-defeat mechanism.

### Correction verification and census

**F-001 / AC-23 and AC-24.** `--root` overrides log.showRoot; explicit first-parent merge diffs and no-renames override diff/merge preferences. The traversal also visits other parents, so paths introduced only on a merged branch are covered. NUL separation preserves quoted, Unicode, tab and newline names. Independent config probing combined log.showRoot=false, log.diffMerges=off, diff.renames=copies, core.quotePath=true, color.ui=always and diff.relative=true: a renamed-away deploy.pem was refused. Instrumentation observed no update-ref or bundle call on refusal. A shallow boundary tree containing deploy.pem was refused too; unavailable ancestors in a safe shallow clone did not leak into its bundle. The shallow fetch limitation is recorded as F-004.

The new history regressions, the original three tip-secret refusals and the no-over-refusal cases pass. All AC-23 tests pass: snapshot parent is the original HEAD, no signature, original index/file hashes/status/HEAD/branches/worktrees unchanged, ignored manifest included by exact path, other ignored tip files excluded, refs/fleet empty even on forced bundle failure. Ignored-file exclusion describes the snapshot tip; its deliberately retained parent/history is not a history scrubber.

**Point 9 / A-21.** Historical matching names can prevent a run even after removal or renaming. This cost and the broad credentials pattern are accurately disclosed. Read-only scans in the implementer's matching receipt find no matching path in either named repo; there is no request to widen the allowlist. A-21 applies the existing rule without changing ancestry, bundle format or dependencies.

**Point 10.** AC-24 is written as a likely-secret-path check with named path fixtures. Neither its pattern chain nor its success cases require blob-content scanning. Ordinary-name committed secrets and secrets in log blobs remain limitations; blob scanning is not a missing correction.

**F-002 / AC-12.** Both POST task and POST status call validate_envelope before their write transactions. The full-object scan includes nested keys and values as well as created/reply_to. The authenticated hello route scans its only variable accepted payload, capabilities; tool keys have a closed vocabulary. Census of stored client input is correct: pair uses a constrained name and SHA-256 digest; hello uses constrained tool names and scanned versions; task/status share complete-envelope validation; project PUT scans the whole manifest; blob PUT is the declared raw-content limitation. Heartbeat/next store a server timestamp or server-generated status, not an unchecked body/header. No sibling persistence route with the same gap was found.

**F-003 / AC-29 and AC-30.** Timeout still returns the existing failed/timeout contract. The actual restricted test's uploaded log contains `fleet: taskkill exit 1, child processes may survive: ERROR: Access denied`. A separate actual-child probe wrote 131072 bytes through the inherited stdout handle, then forced a taskkill refusal: every byte was retained and exactly one warning appended. There is no second file handle, truncating reopen or seek. Child environment inheritance remains unchanged; the AC-30 integration test passes.

**Other binding constraints.** Corrections add no origin, GitHub credential/signing-key flow, push/merge/tag/release action or message-authorized plan transition. Member slot/origin/branch and slot-commit containment tests pass. The source still makes no assignment/removal/override of CLAUDECODE, CLAUDE_CODE_ENTRYPOINT or related variables. No live system, WinRM, prohibited credential file, real repository ref or source file was touched by this review. Synthetic fixtures and all reviewer output were confined to C:/Temp.

### Checklist results and durable observations

Tests used `PYTHONDONTWRITEBYTECODE=1`, `RECEIPTS_DIR=C:/Temp/agentic-framework/receipts`, `AGENT_MODEL_REGISTRY_HOME=P:/.agent`, `-p no:cacheprovider` and an explicit C:/Temp basetemp. The reviewer did not repeat the 45-minute full gate: the corrected full receipt matches independently obtained state, all review input timestamps precede its run, and no input-changing correction was made during this review.

```json
{
  "schema_version": "evidence.v1",
  "check_id": "exec-r2-targeted",
  "cwd": "P:/agentic-framework",
  "scope": "Fleet regression suite including all corrections",
  "phase": "targeted",
  "result": "fail",
  "exit_code": 1,
  "tested_state": "97e8b53ea384633451540fc87abdc40243bfe8744c2bb8061246ad89bdd7f49e",
  "command": "rtk proxy python -m pytest scripts/tests/test_fleet_hub.py scripts/tests/test_fleet_bootstrap.py scripts/tests/test_fleet_run.py -q -rfE -p no:cacheprovider --basetemp C:/Temp/agentic-framework/receipts/dispatch/fleet-mvp-exec-r2/pytest-temp",
  "output": "309 passed, 2 failed in 171.06s. Only test_ac29_a_timeout_kills_the_whole_tree and test_ac29_a_clean_tree_kill_adds_nothing_to_the_log failed, both because taskkill is denied under this restricted account. The uploaded timeout log now reports exit 1 / ERROR: Access denied and child processes may survive. All secret-path/envelope, repo-preservation, parent, slot and environment tests passed."
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "exec-r2-path-probes",
  "cwd": "P:/agentic-framework",
  "scope": "Independent history/config/path/shallow probes",
  "phase": "targeted",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "97e8b53ea384633451540fc87abdc40243bfe8744c2bb8061246ad89bdd7f49e",
  "command": "rtk proxy python C:/Temp/agentic-framework/receipts/dispatch/fleet-mvp-exec-r2/reviewer_probes.py paths",
  "output": "Renamed-away deploy.pem refused with combined log.showRoot=false/log.diffMerges=off/diff.renames=copies/core.quotePath=true/color.ui=always/diff.relative=true, before update-ref or bundle. Unicode, tab and newline paths preserved exactly with NUL separators. Shallow boundary deploy.pem refused. Safe shallow bundle contains no unavailable secret ancestor, but Git cannot fetch it into an empty reader: missing parent / did not send all necessary objects. F-004 records that compatibility limitation."
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "exec-r2-log-probes",
  "cwd": "P:/agentic-framework",
  "scope": "Inherited child log handle, actual restricted timeout log and shallow regression comparison",
  "phase": "targeted",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "97e8b53ea384633451540fc87abdc40243bfe8744c2bb8061246ad89bdd7f49e",
  "command": "rtk proxy python C:/Temp/agentic-framework/receipts/dispatch/fleet-mvp-exec-r2/reviewer_probes.py logs",
  "output": "All 131072 child bytes preserved followed by the exact taskkill exit-1 warning; reason remains timeout. Actual synthetic hub timeout log says child processes may survive: ERROR: Access denied. Shallow fetch failure also reproduces with the pre-correction tip-tree path scan."
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "exec-r2-shallow-objects",
  "cwd": "P:/agentic-framework",
  "scope": "Shallow bundle contents after failed fetch",
  "phase": "targeted",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "97e8b53ea384633451540fc87abdc40243bfe8744c2bb8061246ad89bdd7f49e",
  "command": "rtk proxy python C:/Temp/agentic-framework/receipts/dispatch/fleet-mvp-exec-r2/reviewer_probes.py inspect-shallow",
  "output": "The empty recipient imported four bundle objects before refusing missing ancestry. The unavailable ancestor deploy.pem blob is absent from those objects: no history-secret transport bypass was found."
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "exec-r2-input-audit",
  "cwd": "P:/agentic-framework",
  "scope": "Independent current identity, all referenced receipt hashes and full-run input freshness",
  "phase": "targeted",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "97e8b53ea384633451540fc87abdc40243bfe8744c2bb8061246ad89bdd7f49e",
  "command": "rtk proxy python C:/Temp/agentic-framework/receipts/dispatch/fleet-mvp-exec-r2/reviewer_probes.py audit",
  "output": "All 21 command-linked receipt hashes match, including red corrections, targeted, full, history and package receipts. Current configured identity equals 97e8b53ea384633451540fc87abdc40243bfe8744c2bb8061246ad89bdd7f49e. Full SHA-256 is 6faaf4309c50b21713c2c325f8e7d56e1836d7b82d6911e09f4f4ead5a457339; 4355 passed, 1 skipped, 67 warnings, 36 subtests passed in 2648.38s. Only the work handoff and rolling review have mtimes after the full run started; no code/test inputs do. The configured identity is path-based as disclosed; current fleet.py SHA-256 is 921674e4135c74e5cddb22934187f9439de201f1d4e7bb6855306c4e307c8673."
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "exec-r2-durable",
  "cwd": "P:/agentic-framework",
  "scope": "Fresh matching full-evidence validation",
  "phase": "targeted",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "97e8b53ea384633451540fc87abdc40243bfe8744c2bb8061246ad89bdd7f49e",
  "command": "rtk proxy python core/tools/durable_evidence.py .agent/context/handoffs/2026-11-03-fleet-mvp-handoff.md --require-full --expected-state 97e8b53ea384633451540fc87abdc40243bfe8744c2bb8061246ad89bdd7f49e",
  "output": "OK: durable evidence records. Existing full gate verified; no full-suite rerun claimed."
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "exec-r2-package",
  "cwd": "P:/agentic-framework",
  "scope": "AC-32 package baseline comparison",
  "phase": "targeted",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "97e8b53ea384633451540fc87abdc40243bfe8744c2bb8061246ad89bdd7f49e",
  "command": "rtk proxy python docs/execution/plans/2026-11-03-fleet-mvp/check_package_gates.py",
  "output": "0 problem(s) against baseline head 3a4eac6. Separate --selftest exited 0 and detected a removed baseline failure. Existing refcheck and sanitize reds are not new failures."
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "exec-r2-ac",
  "cwd": "P:/agentic-framework",
  "scope": "All registered ACs accounted for",
  "phase": "targeted",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "97e8b53ea384633451540fc87abdc40243bfe8744c2bb8061246ad89bdd7f49e",
  "command": "rtk proxy python core/tools/validate_closeout_artifacts.py --plan docs/execution/plans/2026-11-03-fleet-mvp/implementation-plan.md --handoff .agent/context/handoffs/2026-11-03-fleet-mvp-handoff.md --ac-coverage-only",
  "output": "OK: all 32 plan AC(s) present in the handoff."
}
```

| Checklist | Result | Observation |
|---|---|---|
| IR-1 | pass | Real localhost TLS hubs, member processes and full run/log/status round trips rerun. Live records stand under D-9; no new live claim. |
| IR-2 | n/a | No new product stub. Taskkill denial is deliberately injected only for its negative-path test/probe. |
| IR-3 / IR-6 | pass | Existing route refusal codes and complete-envelope/hello refusals verified; no new write route or schema. Framework-specific exception class mapping is n/a. |
| IR-4 | pass | History roots/merges/renames/config/encoding/shallow boundary reviewed; persistence census includes the corrected hello sibling. |
| IR-5 | pass | Round 1's per-test grades remain applicable to unchanged tests. New-test grades are below. The two real environmental failures remain visible. |
| IR-7 | pass | All 32 ACs present, integration evidence retained; no new deferral. D-9 remains the human-ruled refresh sequence. |
| DR-1..DR-8 | pass with stated limits | Handoff AC table, changed paths, A-21, corrections, points 9/10 and receipt claims match. The known live version gap and missing deep-history red receipt are disclosed. |

**IR-5 added tests, individually:**

| Test | Grade / observation |
|---|---|
| test_ac12_secret_values_in_other_fields_are_refused | Strong: each existing pattern, HTTP refusal, unchanged rows, absent DB/WAL bytes. |
| test_ac12_a_status_message_is_scanned_the_same_way | Strong: actual claimed task and owner session, exact refusal, no persistence. |
| test_ac12_no_envelope_field_can_carry_a_secret | Adequate: non-None refusal across every field; the HTTP tests supply exact-code and persistence assertions. |
| test_ac12_a_capability_version_is_scanned_too | Strong: real hello HTTP refusal and absent DB/WAL bytes. |
| test_ac24_a_secret_in_the_history_stops_the_run | Strong: four materially different histories, exact refusal, unchanged blob/row counts and empty fleet refs. |
| test_ac24_an_exact_name_deep_in_the_history_stops_the_run | Strong for exact .env and NUL separators: exact CLI failure after intervening commits. Its missing red receipt is accurately disclosed. |
| test_ac24_the_history_scan_finds_a_root_commit_whatever_the_config_says | Strong: actual orphan-root history with log.showRoot=false and exact refusal. |
| test_ac24_an_allowed_name_in_the_history_passes | Adequate: actual acceptance; existing path allowlist tests establish the precise rule. |
| test_ac24_a_secret_on_a_branch_the_bundle_leaves_out_passes | Adequate: acceptance with excluded branch; scope agrees with bundle ref reachability. |
| test_ac29_a_failed_tree_kill_is_written_to_the_log | Strong: actual child output and timeout, only taskkill denial substituted, exact diagnostic assertions. |
| test_ac29_a_clean_tree_kill_adds_nothing_to_the_log | Adequate: actual timeout and no diagnostic in a supported kill environment; correctly fails under this account's real denial. |

### Verdict

`approved` — F-001 and F-002 are fixed, F-003's truthful diagnostic is verified, and no material correction regression or additional secret-check gap was found. The execution achieves its registered LAN handoff/result intent within the approved MVP trust boundary. F-003's restricted-account limitation and F-004's shallow-source limitation are non-blocking. D-1 through D-9 stand; no ruling is reopened and no live refresh is authorized by a message. Stop at this review; the implementing agent copies this receipt into the rolling handoff.

🕐 Completed: 2026-11-04 12:04 (EST)
