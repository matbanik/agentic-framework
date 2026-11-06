---
date: "2026-11-03"
project: "2026-11-03-fleet-mvp"
meus: []
status: "in_progress"
action_required: "VALIDATE_AND_APPROVE"
template_version: "2.2"
verbosity: "standard"
plan_source: "docs/execution/plans/2026-11-03-fleet-mvp/implementation-plan.md"
build_plan_section: "none"
agent: "implementing agent"
reviewer: "codex (cli-dispatch, execution mode, ledger loop exec-2026-11-03-fleet-mvp)"
predecessor: "2026-11-03-fleet-mvp-plan-critical-review.md"
---

# Handoff: 2026-11-03-fleet-mvp-handoff

> **Status**: `in_progress` (implementation and verification done; the execution review approved at round 2)
> **Action Required**: `VALIDATE_AND_APPROVE`

---

## Scope

**MEU**: none (`meus: []`). The plan came straight from a user request.
**Build Plan Section**: none. This package has no `docs/BUILD_PLAN.md` hub; the scope source is
`docs/proposals/2026-11-03-fleet-mvp-outline.md` §3, phases P1 to P3.
**Predecessor**: the plan review, approved at round 2:
`.agent/context/handoffs/2026-11-03-fleet-mvp-plan-critical-review.md`.

**What changed:** <hub host> can hand work to another machine on the LAN and get the result back.

- `.agent/fleet/fleet.py` is one stdlib-only file with the hub, the member loop and the CLI. The
  hub runs on <hub host> at the-hub-LAN-address:8770. It uses TLS with a pinned self-signed certificate, one
  key per member, an append-only SQLite log, and the kinds `ping`, `run` and `agent` (`agent` is
  refused with `kind_not_enabled` until P4).
- `.agent/fleet/bootstrap.md` is the template an agent follows to add a member.
- `core/.agent/fleet.json.template` is the project manifest of named commands.
- Live: <member host> is an approved member, and av-kit's working tree ran there through `setup`,
  `check-py`, `check-ui` and `check-mcp`.

**Not in scope:** the plan's Out of Scope section. No commit, push or merge is part of this work.

---

## Acceptance Criteria

| AC | Type | Description | Source | Test(s) | Status |
|----|------|-------------|--------|---------|--------|
| AC-1 | unit | `validate_envelope` accepts a complete envelope and refuses an extra field, a missing field, a wrong version and a wrong type. | Human-approved (outline §2.3) | `scripts/tests/test_fleet_hub.py`: `test_ac01_accepts_a_complete_envelope`, `test_ac01_refuses_an_extra_field` and 4 more | ✅ |
| AC-2 | unit | `next_state_allowed` is total over `TASK_STATES` × `TASK_STATES`: the test walks every pair, and only `TRANSITIONS` pairs pass. | Human-approved (outline §2.3) | `scripts/tests/test_fleet_hub.py`: `test_ac02_transitions_are_total_over_states`, `test_ac02_terminal_states_have_no_exit` and 1 more | ✅ |
| AC-3 | integration | The store is append-only. | Human-approved (outline §2.7) | `scripts/tests/test_fleet_hub.py`: `test_ac03_update_and_delete_abort_with_append_only`, `test_ac03_append_adds_exactly_one_row_and_changes_none` and 2 more | ✅ |
| AC-4 | unit | Source rules, by AST and text over `fleet.py`: every import is in `sys.stdlib_module_names`; it parses at `feature_version=(3, 11)`; it has no drive-letter path; it does not contain `CLAUDE_CODE_ENTRYPOINT`, `CLAUDECODE` or `cswap`; the default home derives from `Path.home()`. | Human-approved (outline §2.8, A-6, handoff billing rule) | `scripts/tests/test_fleet_hub.py`: `test_ac04_source_rules_hold`, `test_ac04_checker_can_fail` | ✅ |
| AC-5 | integration | A wrong pin stops the client before it writes anything. | Human-approved (D-1) | `scripts/tests/test_fleet_hub.py`: `test_ac05_wrong_pin_stops_status_before_any_byte`, `test_ac05_wrong_pin_stops_pair_before_any_byte` and 1 more | ✅ |
| AC-6 | integration | Authentication on every non-open route. | Human-approved (D-1) | `scripts/tests/test_fleet_hub.py`: `test_ac06_no_key_and_wrong_key_are_unauthorized`, `test_ac06_pending_member_is_not_approved` and 2 more | ✅ |
| AC-7 | integration | Pairing needs a human approval that matches the member's key. | Human-approved (D-1, A-13) | `scripts/tests/test_fleet_hub.py`: `test_ac07_approve_needs_a_tty_and_adds_no_row`, `test_ac07_approve_refuses_piped_stdin` and 9 more | ✅ |
| AC-8 | integration | The hub enforces `SEND_POLICY` and the closed `TASK_KINDS`. | Human-approved (D-2, D-3, outline §2.6) | `scripts/tests/test_fleet_hub.py`: `test_ac08_members_cannot_send_tasks`, `test_ac08_agent_kind_is_not_enabled` and 4 more | ✅ |
| AC-9 | integration | Walking skeleton (outline P1). | Human-approved (outline P1) | `scripts/tests/test_fleet_hub.py`: `test_ac09_ping_round_trip_with_real_processes`, `test_ac09_stopped_member_makes_wait_exit_5` | ✅ |
| AC-10 | integration | Claiming is atomic and a lost claim response is recoverable. | Local Canon (A-6) | `scripts/tests/test_fleet_hub.py`: `test_ac10_concurrent_claims_give_one_working_row`, `test_ac10_repeat_next_returns_the_same_task_and_adds_no_row` and 1 more | ✅ |
| AC-11 | integration | Status posts are owner-checked, transition-checked and idempotent. | Human-approved (outline §2.7) | `scripts/tests/test_fleet_hub.py`: `test_ac11_status_posts_are_owner_transition_and_id_checked`, `test_ac11_status_needs_a_string_state_and_a_status_kind` | ✅ |
| AC-12 | integration | No secret value in a message. Round 1 widened the scan to the whole envelope and to `hello`'s capability versions. | Human-approved (outline §2.6) | `scripts/tests/test_fleet_hub.py`: `test_ac12_secret_values_are_refused`, `test_ac12_secret_values_in_other_fields_are_refused` and 3 more | ✅ |
| AC-13 | integration | Offline delivery and restarts. | Research-backed (outline §2.2; GitHub runners) | `scripts/tests/test_fleet_hub.py`: `test_ac13_task_sent_while_off_reaches_the_member_on_start`, `test_ac13_hub_restart_keeps_pin_and_tasks` and 3 more | ✅ |
| AC-14 | integration | Member restart and stale sessions. | Local Canon (A-7) | `scripts/tests/test_fleet_hub.py` + `scripts/tests/test_fleet_run.py`: `test_ac14_restart_fails_the_members_working_task`, `test_ac14_second_process_makes_the_first_exit_2` and 1 more | ✅ |
| AC-15 | integration | Resource limits (`http.server` caution in `docs/research/fleet/patterns.md`). | Research-backed | `scripts/tests/test_fleet_hub.py`: `test_ac15_raw_client_does_not_stop_requests`, `test_ac15_oversized_json_is_refused` and 1 more | ✅ |
| AC-16 | integration | Only `OPEN_ROUTES` work with no key. | Human-approved (D-1) | `scripts/tests/test_fleet_bootstrap.py`: `test_ac16_open_routes_are_real_routes`, `test_ac16_every_other_route_needs_a_key` and 2 more | ✅ |
| AC-17 | integration | Bootstrap files match the pairing line. | Local Canon (A-16) | `scripts/tests/test_fleet_bootstrap.py`: `test_ac17_served_files_match_the_pairing_line`, `test_ac17_the_hub_saves_the_pairing_line` and 1 more | ✅ |
| AC-18 | integration | `publish` then `check --project` reports missing tools. | Human-approved (outline P2) | `scripts/tests/test_fleet_bootstrap.py`: `test_ac18_publish_then_check_lists_missing_tools`, `test_ac18_check_passes_when_nothing_is_missing` and 8 more | ✅ |
| AC-19 | unit | Template shape. | Human-approved (outline P2) | `scripts/tests/test_fleet_bootstrap.py`: `test_ac19_the_template_has_its_shape`, `test_ac19_the_checker_sees_a_removed_stop_line` and 2 more | ✅ |
| AC-20 | integration | Live, on <hub host>: `FIREWALL_RULE` exists, created by `<hub host>-firewall.ps1` when Mat asks (D-5). | Human-approved (D-1, `the local network notes (lines 145-149)`) | `check_live.py firewall` (live on <hub host>); `the local firewall record fleet-hub-rule-before` and `-after.txt` | ✅ |
| AC-21 | integration | Live: <member host> (outline P2 done). See H1-2 record `live-<member host>`, repeated on the settled `fleet.py` after the D-9 refresh. | Human-approved (outline P2) | `check_live.py <member host>` (live: <hub host> and <member host>) | ✅ |
| AC-22 | unit | `validate_manifest` accepts `core/.agent/fleet.json.template` once its placeholders are filled, and refuses bad shapes. | Local Canon (A-9, A-12) | `scripts/tests/test_fleet_run.py`: `test_ac22_the_filled_template_is_valid`, `test_ac22_the_unfilled_template_is_refused` and 5 more | ✅ |
| AC-23 | integration | The snapshot takes the working tree and leaves the repo alone. | Research-backed (A-3; 2026-11-01 §5) | `scripts/tests/test_fleet_run.py`: `test_ac23_the_bundle_has_the_working_tree_and_not_the_ignored_file`, `test_ac23_an_ignored_manifest_still_travels_and_nothing_else_ignored_does` and 7 more | ✅ |
| AC-24 | integration | A likely secret file stops the run before anything leaves <hub host>. Round 1 widened the check to every path in the bundle's history. | Human-approved (handoff "no secrets") | `scripts/tests/test_fleet_run.py`: `test_ac24_a_likely_secret_stops_the_run`, `test_ac24_an_ignored_secret_and_the_allowed_names_pass` and 5 more | ✅ |
| AC-25 | integration | End to end on a fixture repo with a real hub and member (outline P3). | Human-approved (outline P3) | `scripts/tests/test_fleet_run.py`: `test_ac25_a_command_sees_uncommitted_files_and_its_log_comes_back`, `test_ac25_a_nonzero_exit_fails_and_stops_at_that_argv` and 1 more | ✅ |
| AC-26 | integration | A refused task runs nothing. | Local Canon (A-12) | `scripts/tests/test_fleet_run.py`: `test_ac26_an_unknown_command`, `test_ac26_a_snapshot_with_no_manifest` and 7 more | ✅ |
| AC-27 | integration | Blob integrity and access. | Local Canon (outline §2.5) | `scripts/tests/test_fleet_run.py`: `test_ac27_a_blob_round_trip`, `test_ac27_content_that_does_not_match_the_hash` and 8 more | ✅ |
| AC-28 | integration | Slot properties. | Human-approved (outline §2.5; `P:/av-kit/AGENTS.md:102`; D-4) | `scripts/tests/test_fleet_run.py`: `test_ac28_a_slot_has_no_remote_or_branch_and_is_cleaned`, `test_ac28_a_commit_made_in_the_slot_stays_there_and_is_dropped` | ✅ |
| AC-29 | integration | Timeout and heartbeats. Round 1 added a log line when the tree kill fails. Record `live-f003-timeout` is the run on <member host>. | Local Canon (A-7) | `scripts/tests/test_fleet_run.py`: `test_ac29_a_timeout_kills_the_whole_tree`, `test_ac29_oracle_the_child_writes_its_sentinel_when_not_killed` and 3 more | ✅ |
| AC-30 | integration | The environment reaches child processes unchanged. | Human-approved (handoff billing rule) | `scripts/tests/test_fleet_run.py`: `test_ac30_the_environment_reaches_the_child_unchanged` | ✅ |
| AC-31 | integration | Live: av-kit on <member host> (outline P3 done). The fleet part passes. Three av-kit commands exit 1 on <member host>, reported and not fixed, as this AC says. | Human-approved (outline P3; A-8) | `check_live.py avkit-tools`, `check_live.py av-kit` (live: <hub host> and <member host>) | ✅ |
| AC-32 | integration | Package fit. | Local Canon (`scripts/refcheck.py`, `scripts/sanitize.py`) | `check_package_gates.py`, `check_package_gates.py --selftest`, full pytest gate | ✅ |

<!-- CACHE BOUNDARY -->
<!-- Content above this line is stable across revision passes (KV cache prefix). -->
<!-- Content below this line changes between passes (evidence, results, corrections). -->

---

## Evidence

### FAIL_TO_PASS

| Test | Red Output (hash/snippet) | Green Output | File:Line |
|------|--------------------------|--------------|-----------|
| `test_fleet_hub.py` AC-1 to AC-4 | FileNotFoundError on `fleet.py` at collection, 1 error (`08389b87…`) | passed in `fleet-ac01-04.txt` (`30102baa…`) | `scripts/tests/test_fleet_hub.py` |
| `test_fleet_hub.py` AC-5 to AC-8, AC-12, AC-15 | 1 failed, 48 errors (`7bdd682f…`) | passed in `fleet-ac05-15.txt` (`3f7d711e…`) | `scripts/tests/test_fleet_hub.py` |
| `test_ac09_ping_round_trip_with_real_processes` | condition not met within 40s (`bb5cffa1…`) | passed in `fleet-ac09-14.txt` (`07af75a0…`) | `scripts/tests/test_fleet_hub.py` |
| `test_ac16_open_routes_are_real_routes` | `GET /bootstrap/fleet.py` not a route (`3cd5c919…`) | passed in `fleet-ac16-19.txt` (`560cb4d6…`) | `scripts/tests/test_fleet_bootstrap.py` |
| `test_fleet_run.py` AC-14, AC-25, AC-26, AC-28 to AC-30 | 17 failed, 2 passed (`ad2e9c15…`) | passed in `fleet-ac22-30.txt` (`222d8b6c…`) | `scripts/tests/test_fleet_run.py` |
| `test_ac23_an_ignored_manifest_still_travels_and_nothing_else_ignored_does` (D-8) | the manifest not in the bundle's tree (`46dc8bcb…`) | 128 passed in the file (`222d8b6c…`) | `scripts/tests/test_fleet_run.py` |
| `test_ac24_a_secret_in_the_history_stops_the_run`, 4 histories, and `test_ac24_the_history_scan_finds_a_root_commit_whatever_the_config_says` (F-001) | exit 0: the run went through (`05a85cf8…`) | passed in `fleet-targeted.txt` (`833827d5…`) | `scripts/tests/test_fleet_run.py` |
| `test_ac12_secret_values_in_other_fields_are_refused`, the status and every-field tests, and `test_ac12_a_capability_version_is_scanned_too` (F-002) | HTTP 200 and a stored value (`05a85cf8…`) | passed in `fleet-targeted.txt` (`833827d5…`) | `scripts/tests/test_fleet_hub.py` |
| `test_ac29_a_failed_tree_kill_is_written_to_the_log` (F-003) | the log held only the child's line (`05a85cf8…`) | passed in `fleet-targeted.txt` (`833827d5…`) | `scripts/tests/test_fleet_run.py` |
| Full baseline, 2 tests about the Linux install's lane tests (D-6) | red at row 0, kept in `fleet-first-baseline/` | 4044 passed, 1 skipped (`99b1ccd2…`) | `scripts/instantiate.py`, `core/tools/tests/test_credits_phases.py` |

Row 1's red is a collection error, because the module did not exist yet.
`test_ac24_an_exact_name_deep_in_the_history_stops_the_run` was added after F-001's fix, as a guard on
the `git log -z` separators, so it has no red receipt. The receipts are in
`C:/Temp/agentic-framework/receipts/`; the observations below stand without them.

### Commands Executed

`$R` in the commands is `C:/Temp/agentic-framework/receipts`. Every command ran in Git Bash from
the session's shell, so each uses `> file 2>&1` where the plan's row shows the PowerShell form.

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row0-full-pytest-baseline",
  "cwd": "P:/agentic-framework",
  "scope": "row 0's confirmation over core/tools/tests + scripts/tests after the D-6 fix; not the final gate",
  "phase": "green",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "HEAD 3a4eac6 plus the D-6 fix; before any fleet file was in the repo",
  "command": "export RECEIPTS_DIR=C:/Temp/agentic-framework/receipts AGENT_MODEL_REGISTRY_HOME=P:/.agent; python -m pytest core/tools/tests scripts/tests -q -rfE > $RECEIPTS_DIR/fleet-full-pytest-baseline.txt 2>&1",
  "output": "4044 passed, 1 skipped, 67 warnings, 36 subtests passed in 2390.47s (0:39:50)",
  "receipt_sha256": "99b1ccd2c6779d4255264069f6241a102f6b5ea20a51e6c979533fd162a632ab"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row0-gates-baseline",
  "cwd": "P:/agentic-framework",
  "scope": "refcheck and sanitize --verify failure lines saved for comparison",
  "phase": "static",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "HEAD 3a4eac6 plus the D-6 fix",
  "command": "export RECEIPTS_DIR=C:/Temp/agentic-framework/receipts AGENT_MODEL_REGISTRY_HOME=P:/.agent; python docs/execution/plans/2026-11-03-fleet-mvp/check_package_gates.py --baseline > $RECEIPTS_DIR/fleet-gates-baseline.txt 2>&1",
  "output": "baseline saved, head=3a4eac6, failure lines refcheck 34, sanitize 40",
  "receipt_sha256": "2a6efc90259327e1b0767722a7eec310886da72bded7da08290dabce4fe710b6"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row1-red",
  "cwd": "P:/agentic-framework",
  "scope": "AC-1 to AC-4",
  "phase": "red",
  "result": "fail",
  "exit_code": 2,
  "tested_state": "repo with test_fleet_hub.py and no fleet.py",
  "command": "python -m pytest scripts/tests/test_fleet_hub.py -q -rfE -k \"ac01 or ac02 or ac03 or ac04\" -p no:cacheprovider > $RECEIPTS_DIR/fleet-red-row1.txt 2>&1",
  "output": "FileNotFoundError on .agent/fleet/fleet.py at collection: 1 error in 0.12s. A collection error, the expected form of red when the module under test does not exist.",
  "receipt_sha256": "08389b871101926934bc94f8e371743ef7d3e3bc9dc3eac6b96a7356932bc2a3"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row2-red",
  "cwd": "scratch development copy of the repo (rows 1-6 were built there while the row-0 baseline rerun held the main tree; the files moved into the repo afterwards)",
  "scope": "AC-5 to AC-8, AC-12, AC-15",
  "phase": "red",
  "result": "fail",
  "exit_code": 1,
  "tested_state": "stage-1 fleet.py without the HTTP layer",
  "command": "python -m pytest scripts/tests/test_fleet_hub.py -q -rfE -k \"ac05 or ac06 or ac07 or ac08 or ac12 or ac15\" -p no:cacheprovider --tb=line > $R/fleet-red-row2.txt 2>&1",
  "output": "1 failed, 34 deselected, 48 errors in 5.48s",
  "receipt_sha256": "7bdd682ff918ac6357c1d9ac7753a3feb84e1ca14bc421a62512f4086873cf68"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row3-red",
  "cwd": "scratch development copy of the repo (rows 1-6 were built there while the row-0 baseline rerun held the main tree; the files moved into the repo afterwards)",
  "scope": "AC-9, AC-10, AC-11, AC-13, AC-14",
  "phase": "red",
  "result": "fail",
  "exit_code": 1,
  "tested_state": "fleet.py without the member loop",
  "command": "timeout 150 python -m pytest scripts/tests/test_fleet_hub.py -q -rfE -k \"ac09 or ac10 or ac11 or ac13 or ac14\" -x -p no:cacheprovider --tb=line > $R/fleet-red-row3.txt 2>&1",
  "output": "test_ac09_ping_round_trip_with_real_processes: AssertionError: condition not met within 40s. 1 failed, 87 deselected in 40.38s",
  "receipt_sha256": "bb5cffa16da0547844ca66af2f18eeaf9e88a806ed8188e959591e59144f63f9"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row5-red",
  "cwd": "scratch development copy of the repo (rows 1-6 were built there while the row-0 baseline rerun held the main tree; the files moved into the repo afterwards)",
  "scope": "AC-16 onward",
  "phase": "red",
  "result": "fail",
  "exit_code": 1,
  "tested_state": "fleet.py without the bootstrap routes",
  "command": "timeout 200 python -m pytest scripts/tests/test_fleet_bootstrap.py scripts/tests/test_fleet_run.py -q -rfE -x -p no:cacheprovider --tb=line > $R/fleet-red-row5.txt 2>&1",
  "output": "test_ac16_open_routes_are_real_routes: GET /bootstrap/fleet.py is not a route. 1 failed in 0.05s",
  "receipt_sha256": "3cd5c9192acc4d52f7aad38dbdf8e3d8bbeb0076d2003d9ce4f5caac27d21462"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "row10-red",
  "cwd": "P:/agentic-framework",
  "scope": "AC-14, AC-25, AC-26, AC-28, AC-29, AC-30",
  "phase": "red",
  "result": "fail",
  "exit_code": 1,
  "tested_state": "fleet.py without execute_run",
  "command": "timeout 200 python -m pytest scripts/tests/test_fleet_run.py -q -rfE --tb=line -k \"ac25 or ac26 or ac28 or ac29 or ac30 or ac14\" >> \"$R/fleet-red-row10.txt\" 2>&1",
  "output": "17 failed, 2 passed, 108 deselected in 25.32s",
  "receipt_sha256": "ad2e9c15bf91ce3c360114e221a238c1a627fe35b537142c14cc6ee67a7fc6e9"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "d8-red",
  "cwd": "P:/agentic-framework",
  "scope": "AC-23 ignored manifest (D-8)",
  "phase": "red",
  "result": "fail",
  "exit_code": 1,
  "tested_state": "fleet.py before the force-add",
  "command": "python -m pytest scripts/tests/test_fleet_run.py -k ignored_manifest -q --tb=line -p no:cacheprovider > $RECEIPTS_DIR/fleet-red-ignored-manifest.txt 2>&1",
  "output": "assert '.agent/fleet.json' in ['.gitignore', 'staged.txt', 'tracked.txt', 'untracked.txt'] failed. 1 failed, 127 deselected in 1.87s",
  "receipt_sha256": "46dc8bcbaee34a7b6362e7cd40203a6761900008200017e41181355df8081b99"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "live-firewall",
  "cwd": "P:/agentic-framework",
  "scope": "AC-20",
  "phase": "runtime",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "live <hub host>, rule `Fleet hub 8770`",
  "command": "python docs/execution/plans/2026-11-03-fleet-mvp/check_live.py firewall > $RECEIPTS_DIR/fleet-live-firewall.txt 2>&1",
  "output": "{\"action\": \"Allow\", \"direction\": \"Inbound\", \"profile\": \"Private\", \"remote\": [\"the-LAN-subnet\"], \"protocol\": \"TCP\", \"port\": \"8770\", \"enabled\": \"True\"}; all three firewall profiles on; Plex and FPS-SMB-In-TCP still enabled; check printed: ok",
  "receipt_sha256": "96fab99803990efbd9ab176b897064f5a0462a6e051baf3d4d06c3bee63cb6e0"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "live-d9-refresh",
  "cwd": "P:/agentic-framework",
  "scope": "D-9: row 11 repeated once, after round 2 settled fleet.py",
  "phase": "runtime",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "working tree at the row (HEAD 3a4eac6); hub and <member host> on the settled fleet.py, hash 921674e4135c74e5, after the D-9 refresh",
  "command": "stopped the hub and started it again; run_duper.py <member host>-member.ps1 ACTION=Stop; run_duper.py <member host>-update.ps1; run_duper.py <member host>-member.ps1 ACTION=Restart; python .agent/fleet/fleet.py status > $RECEIPTS_DIR/fleet-status-after-update.txt 2>&1",
  "output": "the hub serves 921674e4135c74e5; <member host>-update.ps1 printed fleet.py updated to 921674e4; the Fleet member service is Running; status lists <member host> online and approved. The firewall rule and the member's key and approval were not touched",
  "receipt_sha256": "fc6ad9d88a326f9c772f21555860f1d1660b42ef9b2416a23bfb8cb101afec8a"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "live-f003-timeout",
  "cwd": "P:/agentic-framework",
  "scope": "AC-29 on the real member, F-003's open check",
  "phase": "runtime",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "working tree at the row (HEAD 3a4eac6); hub and <member host> on the settled fleet.py, hash 921674e4135c74e5, after the D-9 refresh",
  "command": "python .agent/fleet/fleet.py run <member host> --repo P:/av-kit check-py --timeout 5; python .agent/fleet/fleet.py wait <task> --timeout 180 --log $RECEIPTS_DIR/fleet-live-timeout-<member host>.log > $RECEIPTS_DIR/fleet-live-timeout-<member host>.json 2>&1 (exit 1, since the run failed as intended); python <scratchpad>/check_timeout.py > $RECEIPTS_DIR/fleet-live-timeout-check.txt 2>&1",
  "output": "state failed, reason timeout, exit 1, 6.72 s; the log is empty and has no taskkill failure line, so taskkill exited 0 under the member's account on <member host>; the fetched log matches the result's hash; check printed: ok. Whether any child outlived the kill was not inspected on <member host>",
  "receipt_sha256": "80757f7ca40cf78394abb0c912d355bc1134484a8e2e378d5b0f364e9062fc6b"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "live-<member host>",
  "cwd": "P:/agentic-framework",
  "scope": "AC-21",
  "phase": "runtime",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "working tree at the row (HEAD 3a4eac6); hub and <member host> on the settled fleet.py, hash 921674e4135c74e5, after the D-9 refresh",
  "command": "python docs/execution/plans/2026-11-03-fleet-mvp/check_live.py <member host> > $RECEIPTS_DIR/fleet-live-<member host>.txt 2>&1",
  "output": "status lists <member host> as approved and online with its capability report (git 2.56.0, Python 3.14.7); send <member host> ping then wait exited 0; a call from <member host> with no key returned 401; log-collector, firewall profiles and inbound rule count equal before and after; check printed: ok",
  "receipt_sha256": "7a698046957421149fa0694cf4eccaf386c48f5f5d488610db8309c8853741e8"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "live-avkit-tools",
  "cwd": "P:/agentic-framework",
  "scope": "AC-31 tools",
  "phase": "runtime",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "working tree at the row (HEAD 3a4eac6); hub and <member host> on the settled fleet.py, hash 921674e4135c74e5, after the D-9 refresh",
  "command": "python docs/execution/plans/2026-11-03-fleet-mvp/check_live.py avkit-tools > $RECEIPTS_DIR/fleet-live-avkit-tools.txt 2>&1",
  "output": "<member host> reports git 2.56.0, Python 3.14.7, uv 0.13.7, node v26.13.0, npm 11.20.0; check printed: ok",
  "receipt_sha256": "b66124d0849cb712615465a4258603231360e1beb8dad2d08f0af843d2f30cd4"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "live-avkit",
  "cwd": "P:/agentic-framework",
  "scope": "AC-31, the fleet's part",
  "phase": "runtime",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "working tree at the row (HEAD 3a4eac6); hub and <member host> on the settled fleet.py, hash 921674e4135c74e5, after the D-9 refresh",
  "command": "python docs/execution/plans/2026-11-03-fleet-mvp/check_live.py av-kit > $RECEIPTS_DIR/fleet-live-avkit.txt 2>&1",
  "output": "setup completed, exit 0, 52.1 s; check-py failed nonzero_exit, exit 1, 74.5 s; check-ui failed nonzero_exit, exit 1, 90.7 s; check-mcp failed nonzero_exit, exit 1, 13.5 s; all four on tree c1ecc454. No result was rejected. refs/fleet is empty, and the branch and worktree lists equal the before record. check printed: ok",
  "receipt_sha256": "5052c8697fe45a82dbdbef46c0e3df44aa2da845200fc690dde91fff08980893"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "live-avkit-results",
  "cwd": "P:/agentic-framework",
  "scope": "AC-31, what av-kit's own commands reported on <member host>",
  "phase": "runtime",
  "result": "fail",
  "exit_code": 1,
  "tested_state": "working tree at the row (HEAD 3a4eac6); hub and <member host> on the settled fleet.py, hash 921674e4135c74e5, after the D-9 refresh",
  "command": "fetched with wait into $RECEIPTS_DIR/fleet-avkit-check-py.log, fleet-avkit-check-ui.log, fleet-avkit-check-mcp.log",
  "output": "check-py: 404 passed, 1 failed, tests/tooling/test_framework_adoption.py::test_verifier_bootstrap_accepts_captured_bytes (REFUSE: [WinError 2]); -x stopped the run. check-ui: 1128 passed, 1 failed in 1 of 108 files (the first run, on an earlier tree, had 1111 passed and 4 failed). check-mcp: 450 passed, 16 failed in 7 of 34 files. Not diagnosed: AC-31 reports these and does not fix them. They may come from <member host> or from the other session's RC1 work in progress.",
  "receipt_sha256": "bd64b4f33e0f3bbaccb76acf140774db0e4346124a49080bffe9608569202ad6"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "exec-r1-red",
  "cwd": "P:/agentic-framework",
  "scope": "Execution review round 1: F-001, F-002, F-003 regressions",
  "phase": "red",
  "result": "fail",
  "exit_code": 1,
  "tested_state": "fleet.py before round 1's corrections, with the new tests in place",
  "command": "python -m pytest scripts/tests/test_fleet_hub.py scripts/tests/test_fleet_run.py -q --tb=line -p no:cacheprovider --basetemp=C:/Temp/agentic-framework/pt-r1-red -k \"ac12 or ac24 or tree_kill\" > $RECEIPTS_DIR/fleet-red-exec-r1.txt 2>&1",
  "output": "21 failed, 37 passed, 209 deselected in 42.58s",
  "receipt_sha256": "05a85cf833ce2212f75c805245953aef7aed41952dbe532a60b2f36602aa54bc"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "exec-r1-history-probe",
  "cwd": "P:/agentic-framework",
  "scope": "Stop condition 4 under F-001's fix",
  "phase": "static",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "read-only git log over each repo's HEAD",
  "command": "python <scratchpad>/raw_log_probe.py > $RECEIPTS_DIR/fleet-history-secret-probe.txt 2>&1",
  "output": "P:/av-kit and P:/agentic-framework: no secret-named path in the history; no newline in the git log -z output",
  "receipt_sha256": "9e72dfead9b9cdb4a7846fef2769db2da1b6df13797b60645445e69f4bd1b6f8"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "h1-1-unchecked",
  "cwd": "P:/agentic-framework",
  "scope": "H1-1",
  "phase": "static",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "task.md with rows 0-16 done",
  "command": "the row's python -c check > $RECEIPTS_DIR/task-unchecked.txt 2>&1",
  "output": "no implementation row is unchecked; exit 0",
  "receipt_sha256": "13bf7b3039c63bf5a50491fa3cfd8eb4e699d1ba1436315aef9cbe5711530354"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "h1-2-targeted",
  "cwd": "P:/agentic-framework",
  "scope": "Verification Plan §2",
  "phase": "targeted",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "97e8b53ea384633451540fc87abdc40243bfe8744c2bb8061246ad89bdd7f49e",
  "command": "export RECEIPTS_DIR=C:/Temp/agentic-framework/receipts AGENT_MODEL_REGISTRY_HOME=P:/.agent; python -m pytest scripts/tests/test_fleet_hub.py scripts/tests/test_fleet_bootstrap.py scripts/tests/test_fleet_run.py -q -rfE > $RECEIPTS_DIR/fleet-targeted.txt 2>&1",
  "output": "311 passed in 159.50s (0:02:39)",
  "receipt_sha256": "833827d5b9d3e935a87460fde7e500c954747aeba1accca538beb2c672963cb9"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "h1-2-package-gates",
  "cwd": "P:/agentic-framework",
  "scope": "Verification Plan §3, AC-32",
  "phase": "static",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "97e8b53ea384633451540fc87abdc40243bfe8744c2bb8061246ad89bdd7f49e",
  "command": "export RECEIPTS_DIR=C:/Temp/agentic-framework/receipts AGENT_MODEL_REGISTRY_HOME=P:/.agent; python docs/execution/plans/2026-11-03-fleet-mvp/check_package_gates.py > $RECEIPTS_DIR/fleet-package-gates.txt 2>&1",
  "output": "0 problem(s) against baseline head 3a4eac6",
  "receipt_sha256": "1e3706b8e4c335d07e7824051d1650adec1101beff183648d4896e252aea6dd8"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "h1-3-meu-skip",
  "cwd": "P:/agentic-framework",
  "scope": "H1-3",
  "phase": "static",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "97e8b53ea384633451540fc87abdc40243bfe8744c2bb8061246ad89bdd7f49e",
  "command": "the row's python -c check > $RECEIPTS_DIR/meu-skip.txt 2>&1",
  "output": "no .agent/context/meu-status.yaml; exit 0",
  "receipt_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "h1-4-openapi-skip",
  "cwd": "P:/agentic-framework",
  "scope": "H1-4",
  "phase": "static",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "97e8b53ea384633451540fc87abdc40243bfe8744c2bb8061246ad89bdd7f49e",
  "command": "the row's python -c check > $RECEIPTS_DIR/openapi-skip.txt 2>&1",
  "output": "no packages/api; exit 0",
  "receipt_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "h1-2-full-pytest",
  "cwd": "P:/agentic-framework",
  "scope": "Verification Plan §5: core/tools/tests + scripts/tests (row-0 baseline 4044 passed, 1 skipped)",
  "phase": "full",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "97e8b53ea384633451540fc87abdc40243bfe8744c2bb8061246ad89bdd7f49e",
  "command": "export RECEIPTS_DIR=C:/Temp/agentic-framework/receipts AGENT_MODEL_REGISTRY_HOME=P:/.agent; python -m pytest core/tools/tests scripts/tests -q -rfE > $RECEIPTS_DIR/fleet-full-pytest.txt 2>&1",
  "output": "4355 passed, 1 skipped, 67 warnings, 36 subtests passed in 2648.38s (0:44:08)",
  "receipt_sha256": "6faaf4309c50b21713c2c325f8e7d56e1836d7b82d6911e09f4f4ead5a457339",
  "fresh": true,
  "snapshot": false,
  "state_note": "The identity lists paths, not contents. It was taken once this handoff existed, since the run predates the file. No test or code file changed after the run started: see 'Points raised for the reviewer'."
}
```

### Quality Gate Results

```
pytest core/tools/tests + scripts/tests: 4355 passed, 1 skipped, 67 warnings, 36 subtests passed in 2648.38s (0:44:08)
targeted fleet tests: 311 passed in 159.50s (0:02:39)
check_package_gates.py: 0 problem(s) against baseline head 3a4eac6
check_live.py firewall, <member host>, avkit-tools, av-kit: each exit 0, each printed ok
refcheck: not green, 34 lines, all existed at row 0 (listed below)
sanitize --verify: not green, 40 lines, all existed at row 0 (listed below)
```

No pyright or ruff gate: this package's static gates are `refcheck` and `sanitize --verify`
(Verification Plan §3).

### Gate failures that existed before this work, for Mat

These come from row 0, HEAD `3a4eac6`. This plan did not add any: `check_package_gates.py` compares
with this baseline. Quoting the lines here would count as new references, so they are grouped by
source file. `python scripts/refcheck.py` and `python scripts/sanitize.py --verify` print them in full.

`refcheck`, 34 lines at row 0: 31 `UNRESOLVED` references, by source file:

| Source file | Lines |
|-------------|-------|
| `docs/execution/plans/2026-11-03-fleet-mvp/implementation-plan.md` | 9 |
| `core/.agent/skills/deep-research-prompting/SKILL.md` | 7 |
| `docs/execution/plans/2026-11-03-fleet-mvp/task.md` | 6 |
| `docs/proposals/2026-10-31-fleet-nodes.md` | 5 |
| `.agent/context/handoffs/2026-11-03-fleet-handoff.md` | 1 |
| `.agent/context/handoffs/2026-11-03-fleet-mvp-plan-critical-review.md` | 1 |
| `docs/proposals/2026-11-01-remote-hosts.md` | 1 |
| `docs/research/fleet/ai-instructions.md` | 1 |

The other 3 are `UNCLASSIFIED-TOOL` lines for three tool names (`_fw_sync.py`, `fleet.py`,
`remote.py`) cited in `UPDATE-CHECKLIST.md` and `docs/proposals/`.

`sanitize --verify`, 40 lines at row 0: the same 34, plus its own 6: four `VERIFY FAILED` headings
(raw slug, prose model name, reference integrity, tool commands), the raw slug in
`UPDATE-CHECKLIST.md`, and a prose model name in
`core/.agent/skills/deep-research-prompting/templates/d2-gemini.md`.

The plan's and the plan review's lines were references to fleet files that did not exist yet, and
the new files resolve some of them. At this handoff `refcheck` prints 21 such lines: 18 `UNRESOLVED`, none from this plan's files, and 3 `UNCLASSIFIED-TOOL`.

---

## Changed Files

The table lists the work as first handed off. Under D-14 it is committed in four commits, and the
two earlier plan commits are folded into the last of them.

| File | Action | Lines | Summary |
|------|--------|-------|---------|
| `.agent/fleet/fleet.py` | new | 1455 | Hub, store, pairing, member, `ping` and `run` tasks, snapshots, bundles, slots, CLI |
| `.agent/fleet/bootstrap.md` | new | 91 | Template for adding a member, with `STOP FOR HUMAN` lines |
| `core/.agent/fleet.json.template` | new | 9 | Project manifest template |
| `scripts/tests/fleet_harness.py` | new | 219 | Real hub and member subprocesses for the tests |
| `scripts/tests/test_fleet_hub.py` | new | 818 | AC-1 to AC-15 |
| `scripts/tests/test_fleet_bootstrap.py` | new | 281 | AC-16 to AC-19 |
| `scripts/tests/test_fleet_run.py` | new | 865 | AC-14, AC-22 to AC-30 |
| `docs/execution/plans/2026-11-03-fleet-mvp/check_live.py` | new | 313 | Live checks for AC-20, AC-21, AC-31 |
| `docs/execution/plans/2026-11-03-fleet-mvp/check_package_gates.py` | new | 159 | AC-32 baseline comparison |
| `docs/execution/plans/2026-11-03-fleet-mvp/scripts/` | new | 265 | The D-5 prepared scripts for <hub host> and <member host> |
| `core/MANIFEST.md` | modified | +3 | Lists the new package files |
| `scripts/instantiate.py` | modified | +17 | D-6: 17 test files join `RUN_PARAMETERS_WINDOWS_ONLY` |
| `core/tools/tests/test_lane_route_instructions.py` | modified | -19 | D-6: the identity-create test moves out |
| `core/tools/tests/test_credits_phases.py` | modified | +19 | D-6: the identity-create test moves in |
| `docs/execution/plans/2026-11-03-fleet-mvp/implementation-plan.md`, `task.md` | modified | | Rulings D-5 to D-9, AC-23 and AC-31 wording, row states |
| `P:/av-kit/.agent/fleet.json` | new, outside this repo | | av-kit's manifest; uncommitted and excluded (D-7) |

The D-8 change inside the new `fleet.py`, in `make_snapshot`:

```diff
 git(repo, "add", "-A", env=env)
+# The slot reads the manifest from the snapshot, so it travels even if the repo ignores it.
+if (repo / ".agent" / "fleet.json").exists():
+    git(repo, "add", "-f", "--", ".agent/fleet.json", env=env)
 tree = git(repo, "write-tree", env=env)
```

The D-6 change in `scripts/instantiate.py` (17 lines of this form):

```diff
     "tools/tests/test_worktree_layout.py",
+    "tools/tests/test_lane_route_tooling.py",
+    "tools/tests/test_lanes_acceptance.py",
 )
```

---

## Codex Validation Report

_Left blank for reviewer agent._

### Corrections Applied

Round 1 returned `changes_required`. The review's own log is in
`.agent/context/handoffs/2026-11-03-fleet-mvp-implementation-critical-review.md`.

| Finding | Fix in `.agent/fleet/fleet.py` | New tests |
|---------|-------------------------------|-----------|
| F-001, AC-24 | New `bundle_paths`: `git log --root --diff-merges=first-parent --no-renames --name-only -z` from the snapshot commit. `make_snapshot` applies the same patterns and allow list to that list, in place of the tip tree's `ls-tree`, before any ref or upload | `test_ac24_a_secret_in_the_history_stops_the_run` (staged out and ignored, deleted later, renamed away, only in a merge); root commit with `log.showRoot` off; exact name deep in the history. Two no-over-refusal tests: an allowed name in the history, and a secret on a branch the bundle leaves out |
| F-002, AC-12 | `validate_envelope` scans the whole envelope. `validate_hello` scans the capability versions, which is the same gap found by the census | `test_ac12_secret_values_in_other_fields_are_refused`; `test_ac12_a_status_message_is_scanned_the_same_way`; `test_ac12_no_envelope_field_can_carry_a_secret`; `test_ac12_a_capability_version_is_scanned_too` |
| F-003, non-blocking | New `kill_tree` writes a line to the run's log when `taskkill` exits nonzero, with its exit code and message, and says child processes may survive. The reason stays `timeout`, as AC-29 says | `test_ac29_a_failed_tree_kill_is_written_to_the_log`; `test_ac29_a_clean_tree_kill_adds_nothing_to_the_log` |

**Census.** Every route that stores client data: `pair` takes a checked name and a hex digest;
`hello` was the sibling, now fixed; `POST` task and status share `validate_envelope`; the manifest
was already scanned whole; blobs are the stated limitation in AC-12. Every route to a bundle:
`make_snapshot` is the only one, and `publish` sends the manifest alone.

**Cross-doc sweep.** `bootstrap.md` and the template do not describe the scan's extent, so they
are unchanged. The plan's AC-12 and AC-24 name fewer cases than the code now covers. This workflow does not edit
the plan, and the wider code still satisfies both.

**F-003 on the real member.** Done at the D-9 refresh: one `run --timeout 5` on <member host> ended `failed`,
reason `timeout`, with no taskkill failure line in its log (record `live-f003-timeout`). Under the
reviewer's restricted account, `test_ac29_a_timeout_kills_the_whole_tree` and
`test_ac29_a_clean_tree_kill_adds_nothing_to_the_log` still fail because taskkill is denied there,
as round 2 reports; the log now says so when that happens.

### Points raised for the reviewer

1. **D-5 to D-9 were added during execution**, after plan approval, and have not been reviewed.
   This review covers them.
2. **D-9:** the refresh ran once, after round 2 approved. The hub and <member host> now serve and run hash
   `921674e4135c74e5…`, and rows 11 and 14's checks were repeated on it (records `live-d9-refresh`,
   `live-<member host>`, `live-avkit-tools`, `live-avkit`, `live-avkit-results`). `live-firewall` was not
   repeated, since the refresh does not touch the rule. The first row 14 receipts, on hash
   `644262a9988c0ebf…`, are kept in `row14-first/` under the receipts folder. Rounds 1 and 2 reviewed
   those first results, not these.
3. **D-8 came before its ruling.** The first row 14 attempt was rejected with `no_manifest`; the
   change was made, then reported. M-8 asks for the ruling first. Mat accepted it afterwards.
4. **Reduced coverage (D-6):** 17 lane and run-parameter test files no longer ship to non-Windows
   installs.
5. **`pair` over WinRM** departs from "keys created by a human at the console"; Mat chose this in
   D-5. `approve` stays with Mat in a real terminal.
6. **Additions to the plan's design:** the hub saves `pairing.txt`, `members` has a `capabilities`
   column, and `<member host>-member.ps1` takes `ACTION=` rather than `-Stop` style flags (recorded in the plan).
7. **Full-gate identity:** the identity lists paths, not contents. The round 2 run started after
   the last code and test edit. A listing taken when it ended showed no file under `.agent`, `core`,
   `scripts` or `docs` newer than a marker made as it started. After the run, only this handoff,
   the review file and `task.md`'s row states changed.
8. **`check-py`'s `-x`** stopped at the first failure, and `check-ui`/`check-mcp` stop at their
   test step, so av-kit's builds never ran on <member host>. `run_steps` stops at the first nonzero step by design.
9. **F-001's cost (A-21):** a repo whose reachable history holds a secret-named path cannot run
   until the history or the allow list changes. The patterns are by name, and `*credentials*` is broad.
10. **Ancestor contents are checked by path only**, as the tip always was. A secret committed under
    an ordinary name still travels. AC-24 is a path check, and scanning every blob is more machinery
    than this MVP asked for.

---

## Deferred Items

- **F-004, a stated limitation (A-22).** A source repo needs its full local history. From a
  shallow clone, `make_snapshot` builds a bundle an empty member cannot fetch, so the member reports
  `bundle_bad` and the run fails. Round 2 raised it as non-blocking, and the older scan had the same
  gap. If a shallow source ever matters, the fix is a refusal before upload; rebuilding the history
  is not needed.
- **The D-7 av-kit manifest commit** is ruled and listed in the plan, and waits for Mat's word.
- **Hashes in this record.** `8621e3a` and `3a4eac6` were the two local plan commits, folded under
  D-14 and never pushed, so a clone cannot resolve them. The evidence records and the review keep
  them, because they are literal output of those runs.
- **Files that stay local under D-13 and D-15.** The plan's `scripts/` folder and `check_live.py`,
  two proposals, `docs/research/fleet/` and the first fleet handoff are cited here and are not in
  the repo.
- **A lane worktree based on the old `main`.** Uncommitted lane work sits on the old `15c9872`. The
  corrected commit has the same tree, so that work rebases onto the new `main` without conflict
  when it lands.

---

## Decision Log

<!-- Every .agent/docs/human-decision-protocol.md decision made during this MEU, autonomous or human-ruled, as ONE fenced decision_log: YAML block with the plan's entry shape, or exactly `None.` (delete the example below in that case). This comment may stay; any other prose here is refused. The closeout validator reconciles every entry with the reflection's Decisions Log; an example left unfilled is refused, not ignored. -->

```yaml
decision_log:
  - id: D-5
    stage: execution
    question: "How do the human rows run, and how is <member host> reached?"
    resolution: human
    class: two-way
    chosen: "Each human step is a prepared script that the agent runs when Mat asks, and <hub host>-firewall.ps1, the one that needs elevation, runs in its own elevated window through a UAC prompt. <member host> is reached over WinRM with the local WinRM helper. No agent CLI on <member host> until P4. pair runs over WinRM. approve stays with Mat in a real terminal. The member runs as one named, triggerless scheduled task"
    source_tag: Human-approved
    precedents: ["the local network notes (lines 145-149) — named, reversible changes on <member host>", "plan A-7 — no autostart", "handoff §3 — keys created by a human at the console: pair over WinRM departs from this, flagged in User Review Required"]
    research: { engine: none, sources: ["C:/Temp/agentic-framework/receipts/<member host>-probe.txt — read-only WinRM probe of <member host>"] }
    reasoning: "Mat replaced the console steps with scripts the agent runs on request. A process started in a WinRM shell dies with it, so the member needs one named task. A task with no trigger keeps A-7. The WinRM user and the console user differ, so pair and member both run as the WinRM user. A window reload does not elevate Cursor, and a real elevated relaunch would end every other Cursor session, so Mat chose the UAC prompt"
    human_message_reference: "USER_EXPLICIT 2026-11-03 'check [the local ops folder] on how to access <member host> with winrm / rather than commands prepare script to be run in elevated prompt. I will elevat the IDE and ask you to run them for me.'; USER_EXPLICIT 2026-11-04 'yes use the UAC prompt for <hub host>-firewall.ps1'"
  - id: D-6
    stage: execution
    question: "The row-0 baseline was red in two tests about the Linux install's copy of the lane tests, which this plan had not touched. Stop, or fix them first?"
    resolution: human
    class: two-way
    chosen: "Fix them first, then re-confirm with a full run. RUN_PARAMETERS_WINDOWS_ONLY in scripts/instantiate.py gains the 17 lane and run-parameter test files that import a fixture the non-Windows install removes, and the identity-create test moves from test_lane_route_instructions.py to the Windows-only test_credits_phases.py"
    source_tag: Human-approved
    precedents: ["plan stop condition 1"]
    research: { engine: none, sources: ["C:/Temp/agentic-framework/receipts/fleet-first-baseline/", "C:/Temp/agentic-framework/receipts/fleet-full-pytest-baseline.txt"] }
    reasoning: "The rerun ended 4044 passed, 1 skipped. The cost is stated: those lane and run-parameter tests no longer ship to non-Windows installs. These three files are outside the plan's list and stay uncommitted"
    human_message_reference: "USER_EXPLICIT 2026-11-03 answer 'Fix them first' to the red baseline question"
  - id: D-7
    stage: execution
    question: "Another av-kit session excluded P:/av-kit/.agent/fleet.json from its RC1 commit until Mat decides. What happens to the file?"
    resolution: human
    class: product-preference
    chosen: "Keep it local and leave that exclude line through RC1. Commit it as its own small av-kit commit once fleet.py is committed here, on Mat's separate word"
    source_tag: Human-approved
    precedents: ["docs/proposals/2026-11-03-fleet-mvp-outline.md:259 — each project's manifest lives in its repo", "this plan, 'Two files land outside this repo' — left for Mat to keep or delete"]
    research: { engine: tavily, sources: ["https://git-scm.com/docs/gitignore/2.9.5 — info/exclude is for files specific to one user's workflow", "https://gitbybit.com/gitopedia/best-practices/atomic-commits — commit unrelated changes separately", "https://blog.vincentqiao.com/en/posts/claude-code-settings-intro — shared config is committed, personal overrides are not"] }
    reasoning: "The design puts the manifest in the repo, but today it serves a tool that is not committed and has nothing to do with RC1. Committing it in RC1 mixes unrelated work; deleting it stops av-kit running on the fleet"
    human_message_reference: "USER_EXPLICIT 2026-11-04 'all accepted'"
  - id: D-8
    stage: execution
    question: "The first row 14 runs were rejected with no_manifest because av-kit ignored its manifest. Should the snapshot carry an ignored manifest?"
    resolution: human
    class: two-way
    mandatory: [M-8]
    chosen: "Yes: after add -A, make_snapshot force-adds .agent/fleet.json by exact path to its temporary index. No other ignored file travels"
    source_tag: Human-approved
    precedents: ["AC-23 — ignored files stay out of the snapshot; this is a narrow exception"]
    research: { engine: tavily, sources: ["https://github.com/superfly/flyctl/issues/2245 — quotes Docker's docs that an ignored Dockerfile is still sent because the daemon needs it; flyctl left it out and failed the same way"] }
    reasoning: "The member cannot run without the manifest. Refusing at run would force the exclude line out, which risks the file entering the RC1 commit. Sending the manifest in the task needs more code and a <member host> update. The change was made before the ruling and reported to Mat"
    human_message_reference: "USER_EXPLICIT 2026-11-04 'all accepted'"
  - id: D-9
    stage: execution
    question: "D-8 changed fleet.py after row 11. When do <member host> and the hub get the updated file?"
    resolution: human
    class: two-way
    mandatory: [M-10]
    chosen: "Once, at closeout, after the execution review settles the file, by repeating row 11's sequence. Row 14 repeats then only if a review correction changed fleet.py after its receipts"
    source_tag: Human-approved
    precedents: ["task.md row 11", "plan stop condition 2"]
    research: { engine: none, sources: [] }
    reasoning: "D-8 runs only on <hub host>, so <member host> behaves the same until then, and the review may change the file again"
    human_message_reference: "USER_EXPLICIT 2026-11-04 'all accepted'"
  - id: A-21
    stage: execution
    question: "Execution review F-001: how does the secret-path check cover the bundle's history?"
    resolution: autonomous
    class: two-way
    chosen: "Scan every path in the snapshot's history with the existing patterns and allow list, and refuse the run. Keep the parent commit and the full bundle"
    source_tag: Local Canon
    precedents: ["AC-23 and AC-24", "execution review round 1, F-001's recommendation", "plan stop condition 4"]
    research: { engine: none, sources: [] }
    reasoning: "It is the reviewer's recommendation, uses no new pattern or dependency, and leaves AC-23's parent as it is. Neither av-kit's nor this repo's history holds a matching path, so stop condition 4 is not reached. Cost: a repo whose history holds such a path cannot run until the history or the allow list changes, and the second needs Mat's word"
  - id: A-22
    stage: execution
    question: "Execution review F-004, non-blocking: does the settled fleet.py change so a shallow source repo is refused before upload?"
    resolution: autonomous
    class: two-way
    chosen: "No code change. Full local history is a stated prerequisite of a source repo, recorded in Deferred Items"
    source_tag: Local Canon
    precedents: ["execution review round 2, F-004's recommendation", "task row H1-2: row 11 repeats once after the review settles fleet.py", "the human's simplicity principle"]
    research: { engine: none, sources: [] }
    reasoning: "The reviewer's recommendation is to document it and calls a refusal optional. The failure is not silent: the member reports bundle_bad and the run ends. A refusal would change fleet.py after approval, which means another review, another refresh and another live pass, for a case neither live repo has. Cost: a shallow clone fails after its upload, with a less direct reason"
  - id: D-12
    stage: closeout
    question: "Commits carry a personal address rather than the noreply one. Which commits are corrected?"
    resolution: human
    class: one-way-door
    mandatory: [M-1, M-12]
    chosen: "The unpushed ones only: 15c9872 keeps its tree, message and dates and is signed again under the noreply address. The pushed history stays as it is, and Mat checks GitHub's email privacy settings"
    source_tag: Human-approved
    precedents: ["the global commit identity rule, which leaves a rewrite to the user"]
    research: { engine: tavily, sources: ["https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository — rewritten commits can stay reachable by SHA in cached views", "https://docs.github.com/en/account-and-profile/how-tos/email-preferences/blocking-command-line-pushes-that-expose-your-personal-email-address — the block checks only the most recent commit", "https://docs.github.com/en/account-and-profile/how-tos/email-preferences/setting-your-commit-email-address — earlier commits keep their earlier address"] }
    reasoning: "It stops further exposure at low cost and stays reversible until a push. Rewriting the pushed history changes every hash and still may not remove the address from cached views. Leaving it would publish more commits that break the rule. The two plan commits predate the config change, which is why they carried the old address; the check before committing was missed"
    human_message_reference: "USER_EXPLICIT 2026-11-04 'all accepted'"
  - id: D-13
    stage: closeout
    question: "What from this work goes in a public repo, which so far holds no LAN address?"
    resolution: human
    class: one-way-door
    mandatory: [M-12]
    chosen: "The code and scrubbed records. The LAN address and subnet, the local ops paths and the log collector's product name become plain words; the prepared scripts and check_live.py stay local. Machine names and the use of WinRM stay"
    source_tag: Human-approved
    precedents: ["scripts/sanitize.py — the published package already replaces real project strings"]
    research: { engine: tavily, sources: ["https://blog.gitguardian.com/how-we-got-a-cisa-github-leak-taken-down-in-26-hours — a far larger leak, in which hostnames were part of the concern; weak evidence, and nothing closer was found"] }
    reasoning: "More can be published later and nothing can be taken back. Publishing everything is simplest and holds no credential, but it would map the LAN for good. Making the scripts take the address as a parameter would change reviewed code for files that have done their job. The scrub came after the approved review and is wording only, so it was shown to Mat rather than sent for another round"
    human_message_reference: "USER_EXPLICIT 2026-11-04 'all accepted'"
  - id: D-14
    stage: closeout
    question: "What shape do the commits take?"
    resolution: human
    class: two-way
    mandatory: [M-8]
    chosen: "Four commits, the D-6 fix first because the full gate is red without it, then test, feat and docs. The two plan commits fold into the docs commit. No AI trailer. Evidence records keep the old hashes as literal output, with a note in Deferred Items"
    source_tag: Human-approved
    precedents: ["plan D-6 — its files were left out only because the plan's list did not hold them"]
    research: { engine: none, sources: [] }
    reasoning: "Folding takes the fewest steps, and both plan commits needed the address fix and the scrub anyway. Keeping them separate would save the record that the plan came before the code, but needs a content rebase. Adding the draft on top would publish both problems"
    human_message_reference: "USER_EXPLICIT 2026-11-04 'all accepted'"
  - id: D-15
    stage: closeout
    question: "What happens to the inputs this work read and nothing had committed?"
    resolution: human
    class: two-way
    mandatory: [M-12]
    chosen: "Commit the outline, scrubbed, because the plan names it as the scope source. Keep the other seven files local"
    source_tag: Human-approved
    precedents: ["Mat's 2026-11-03 ruling that the research drafts are reference material"]
    research: { engine: none, sources: [] }
    reasoning: "The scope reference then resolves in a clone. Committing all of them publishes drafts Mat set aside. Committing none leaves the plan's scope reference broken"
    human_message_reference: "USER_EXPLICIT 2026-11-04 'all accepted'"
```

---

## History

| Event | Date | Agent | Detail |
|-------|------|-------|--------|
| Created | 2026-11-04 | implementing agent | Rows 0-16 done; H1-2 passed fresh |
| Submitted for review | 2026-11-04 | implementing agent | To Codex, ledger loop `exec-2026-11-03-fleet-mvp`, round 1 |
| Round 1 result | 2026-11-04 | codex | `changes_required`: F-001, F-002 blocking; F-003 non-blocking |
| Corrections applied | 2026-11-04 | implementing agent | F-001, F-002, F-003; targeted and full gates fresh |
| Submitted for review | 2026-11-04 | implementing agent | Round 2 |
| Round 2 result | 2026-11-04 | codex | `approved`, 0 blocking; F-001, F-002 fixed; F-003 accepted risk; F-004 open and non-blocking |
| D-9 refresh | 2026-11-04 | implementing agent | Hub and <member host> on `921674e4135c74e5…`; live checks repeated; F-003 run on <member host> |
| Rulings D-12 to D-15 | 2026-11-04 | Mat | Address, publication, commit shape and inputs; scrub and four commits, no push |
