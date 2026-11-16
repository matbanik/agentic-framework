---
date: "2026-11-15"
review_mode: execution
target_plan: "docs/execution/plans/2026-11-15-usb-kit-usability/implementation-plan.md"
round: 2
verdict: approved
requested_verbosity: standard
findings_count: 0
template_version: "2.2"
agent: "gpt-6.1-sol"
---

# Critical Review: 2026-11-15-usb-kit-usability

> **Review Mode:** execution. **Round:** 1 of 6. **Verdict:** `changes_required`.
>
> **Intent anchor:** "Make the USB kit usable on every fleet member: members send their record to the hub over HTTP, the Ubuntu sudo-rs elevation chain works, the prerequisites install, and GUI members get RustDesk."
> **Intent achieved:** partial. The implementation supplies the intended flow, but two reproducible paths still defeat record recovery or tool availability.

## Findings

All findings have High confidence. F-001 and F-002 block; F-003 and F-004 do not. All are `finding_kind: behavior`, with `mechanism: null`.

| # | Severity | Blocking | Kind | Finding | File:Line | Recommendation | Status |
|---|---|---|---|---|---|---|---|
| F-001 | High | yes | behavior | **A Windows child that dies after the last checkpoint produces an invalid recovery record (AC-2).** When the child's checkpoint already contains every step through `host_key`, with no failed step, the parent copies those steps and appends another `elevate`. `read_record` rejects the repeated id. This is reachable while the child collects versions after the last checkpoint, before finalization; the recovered host key and completed work then cannot be received or imported. | `.agent/fleet/usb/setup-windows.ps1:932-949`; version collection at `:863-869`; rejection at `.agent/fleet/usb/fleet_usb.py:482-483` | Change an existing step's result, or otherwise represent this failure without duplicating a step id. Add the last-step-checkpoint case and require the recovered record to pass `read_record`. | fixed |
| F-002 | High | yes | behavior | **An existing snap PowerShell is reported installed but remains unavailable to SSH (AC-10).** The early return when `/snap/bin/pwsh` exists bypasses creation of `/usr/local/bin/pwsh`. The Account and intended SSH PATH omit `/snap/bin`; version collection nevertheless records PowerShell by trying its absolute snap path. The independent fixture exits 0 with `pwsh: ok` and a version, while the SSH-PATH lookup exits 1. | `.agent/fleet/usb/setup-unix.sh:493-500`, `:546-550`, `:617`; current fresh-install tests at `scripts/tests/test_fleet_usb.py:917-925`, `:991-1007` | Ensure an existing snap installation gets the same link as a fresh installation. Cover a preinstalled snap with no existing link and check SSH-PATH lookup. | fixed |
| F-003 | Medium | no | behavior | **EA-8's nonzero `--config` recovery is implemented only on Windows.** Unix immediately fails the RustDesk step, before the TOML read-back and fallback. A stub returning 1 confirms that neither the fallback file nor a restart occurs. No real-member occurrence was established, so this is not an additional blocker. | `.agent/fleet/usb/setup-unix.sh:980-990`; compare `.agent/fleet/usb/setup-windows.ps1:678-687`; `docs/execution/plans/2026-11-15-usb-kit-usability/task.md:130` | Apply the stated read-back/fallback behavior on Unix too, retaining the command diagnostic; add a nonzero-config case. | fixed |
| F-004 | Medium | no | behavior | **EA-12 does narrow privacy coverage beyond its two fixtures.** Allowing the entire link-local range means a real host's link-local endpoint in any scoped file passes class 1. Class 5 adds names, ids and host-key bodies, but does not add member addresses. The synthetic endpoint probe yields no hit. Link-local addresses serve real interfaces; RFC 3927 also explicitly discusses privacy when they leave the local link. No actual machine-address leak was established in this tree, so this tooling observation does not block. | `docs/execution/plans/2026-11-15-usb-kit-usability/check_kit.py:388-400`, `:444-459`; `task.md:134`; `implementation-plan.md:291-292` | Keep any exemption confined to the verified synthetic fixtures, rather than all scoped text; correct the claim that these addresses name no machine. | fixed |

F-004 concerns committable tooling; the other findings concern the deliverable. The closed vocabulary supplies no applicable mechanism for F-004, so it is reported as behavior. RFC support: [RFC 3927, sections 1 and 2.10](https://www.rfc-editor.org/rfc/rfc3927#section-2.10).

## Scope

Reviewed the named implementation plan, task and EA-1 through EA-13, the correlated evidence handoff and its reviewer points, all 12 tracked modifications against HEAD `a73d6df2f327e977ca91d86a93c25c37fcfc2a7b`, and the four named untracked test/checker files. Read current product files directly and captured the three product-code diffs; inspected launcher, README, bootstrap, MANIFEST and known-issue changes. Consulted the durable-evidence, closeout and task-lint implementations for their actual predicates.

This is one project handoff with `meus: []`. The superseded plan and its review were excluded. The five human rows remain human gates. No live mode, member connection, hub connection, port 8771 listener, fleet task, credential-store inspection, commit or product edit was performed. The receiver tests used ephemeral loopback ports and temporary fixture homes.

## Checklist Results

### Runtime, contracts and test rigor

| Check | Result | Observation |
|---|---|---|
| IR-1 integration evidence | pass within agent scope | AC-14 uses actual HTTP requests and on-disk round trips, with no mocked HTTP transport. Live AC-23 through AC-26 remain unrun human gates. |
| IR-2/IR-3 | n/a | No application repository stub or application-route error mapping is in scope. Receiver errors were audited under IR-6. |
| IR-4 generalization | partial | Unix and Windows share the delivery contract; F-003 identifies a recovery difference. |
| IR-5 assertion strength | pass with coverage gaps identified | Audited every current Python test function and Pester `It` block. Each has a meaningful assertion or asserted helper. Grade **Strong** unless covered by the Adequate exceptions below. Missing cases behind F-001/F-002 are coverage gaps, not claims that existing tests are incapable of failure. |
| IR-6 write boundaries | pass for enumerated cases | Record keys, identities, statuses, delivery, body length, token, malformed bodies, refusal non-writes and atomic replacement have substantive assertions. No additional hardening requested. |
| IR-7 coverage and deferral | partial | All 26 ACs appear in the handoff. F-001/F-002 prevent an unqualified agent-AC pass. Human rows have their named B blocks and durable follow-ups. |
| DR-1 through DR-4, DR-6 through DR-8 | partial | Product/doc changes are real; README supplies hub, member, import and macOS permission steps. F-003/F-004 qualify amendment claims. Handoff distinguishes live work from completed work. |
| DR-5 reproducibility | partial | Independent Python subset passes; fresh Pester attempt stops at the runner self-check. Matching author Pester evidence remains available. |

**Adequate test grades:** `test_ac04_read_record_accepts` checks acceptance and identity/version rather than complete returned-object equality; the documentation tests at `test_fleet_usb.py:2683-2746` largely check required text, with the firewall and bootstrap tests checking relevant context. Pester's tool-version aggregation test at `SetupWindowsUsb.Tests.ps1:387-406` checks the aggregator with a mocked version provider. The other tests exercise specific values, step results, command arguments/order, negative paths, file bytes or round trips. No current test was classified Weak. These grades do not establish real installer or GUI compatibility.

### AC disposition

| ACs | Disposition and evidence |
|---|---|
| AC-1 | Implemented: checkpoints, caught errors, signals and forced-kill checkpoint are asserted at Python lines 190-261. |
| AC-2 | **Partial, F-001:** ordinary success/failure, interruption, elevation cancellation and earlier child checkpoint are covered; terminal child checkpoint is broken. |
| AC-3, AC-4 | Implemented: matching name cases, v1/v2 acceptance/refusal and JSON escaping; independent subset passed. |
| AC-5, AC-6 | Implemented: idempotent User PATH and failed missing tool; import distinguishes failed delivery, failed setup and incomplete records. |
| AC-7, AC-8, AC-9 | Implemented within stub contract: elevator order/fallback codes, repair, account environment, visudo fallback and plain-bash launchers. Actual sudo-rs remains a live check. |
| AC-10 | **Partial, F-002:** fresh apt/dnf, snap/tarball and user installers are covered; preinstalled snap lacks the required SSH reachability. |
| AC-11, AC-12 | Implemented within mocks/stubs: winget flags/exits, registry PATH, Homebrew account/order and SSH shell environment. |
| AC-13, AC-14 | Implemented; independent preparation/HTTP acceptance/refusal/count/timeout/import tests passed. |
| AC-15 | Implemented within mocks/stubs: pending checkpoint, ordered retry, null delivery body, offline import and interrupted-send persistence. |
| AC-16, AC-19 | Implemented within fake downloads/SSH; independent subset passed. Real download and cross-system SSH behavior remain live risks. |
| AC-17, AC-18 | Enumerated mocked/stubbed installation, readiness, fallback and macOS restart cases are covered. F-003 qualifies the extra EA-8 recovery claim. |
| AC-20, AC-21 | Implemented; documentation and six-issue render checks passed independently. |
| AC-22 | Matching package-gate receipt reports zero new baseline failures; selftest passes 57/57. F-004 qualifies privacy coverage. |
| AC-23 through AC-26 | Human rows 12-15, unrun. README and live checker supply fresh receive/run-id matching, full-access import, SSH versions, RustDesk id/password-file checks and rerun comparisons. No live success claimed. |

### Execution amendments

| Amendment | Holds? | Assessment |
|---|---|---|
| EA-1 | yes | Rewording does not change computed-address filtering. |
| EA-2 | yes | Human waiver is explicit. Baseline and final receipts fail exactly the same three ids; known entries must still run and fail. Neither excused test file changed. |
| EA-3 | yes, as an explicit adjustment | Homebrew now needs account; it still runs after admin-rights processing. This allows independent prerequisites to proceed after an SSH failure, consistent with nonfatal setup. No test assertion is bypassed. |
| EA-4 | yes | Additional winget success code, Store-alias filtering, uv wrapper and mock setup preserve the intended checks. Real winget remains for live validation. |
| EA-5 | yes | URL deduplication, v2-only receive, offline fallback and errors are supported by implementation/tests. |
| EA-6 | yes | Delivery preparation, retry, interruption and exit-code separation agree with code. |
| EA-7 | yes within tested boundary | Settings validation/reuse, fixture downloads, password reuse and stdin transport have meaningful tests. Real vendor APIs and remote quoting remain unproved. |
| EA-8 | partial | The changed AC-11 expected list adds only `rustdesk` before `host_key`, as required by AC-17; the red receipt retains the earlier expected list. This assertion change is justified. The nonzero-config claim fails on Unix: F-003. |
| EA-9 | yes | `persist()` changes stub setup so the ordering test covers the no-fallback path. Assertions still require exactly one system bootstrap, before id lookup and after bootout. Separate fallback and rerun tests assert reloading both jobs. This is an allowed setup change under G36. |
| EA-10 | yes | Adding the two waived tests to the targeted selection preserves the gate's missing-test refusal. |
| EA-11 | yes | A checked no-op status fits the linter's four-state enum; row text still withholds commit authority. |
| EA-12 | partial | Reference rewording, direct base initializer and invalid-version fixture preserve behavior. The blanket address exemption does narrow coverage: F-004. |
| EA-13 | yes for this review | Excludes only this task file from the stated package identity, avoiding status-mark churn. Product, tests, plan and checker remain hashed. Task contents and B blocks were reviewed separately. Independent hashing matches the full-run state. |

### Evidence observations

The following are durable reviewer observations; receipt names alone are not their evidence. Executables were resolved locally; personal installation paths are omitted. Python targeted tests used the first explicit executable returned by `where.exe python`, after an initial generic child invocation selected an interpreter without pytest.

```json
{"schema_version":"evidence.v1","check_id":"review-targeted","cwd":"P:/agentic-framework","scope":"AC-4,13,14,16,19,20,21","phase":"targeted","result":"pass","exit_code":0,"tested_state":"b4398138871f19f3a5559343965bc4e1e8b5a4ede3675fa98d34e68376a33880","command":"python -m pytest scripts/tests/test_fleet_usb.py -q -ra -p no:cacheprovider --basetemp C:/Temp/agentic-framework/receipts/dispatch/uk2-exec-review/pytest-temp -k 'ac04 or ac13 or ac14 or ac16 or ac19 or ac20 or ac21'","output":"116 passed, 113 deselected in 4.60s","receipt_sha256":"fedc8256df6579cfa07012c335a599251adbb5f4b72ac5438c39c65d165a5d79"}
```

```json
{"schema_version":"evidence.v1","check_id":"review-selftest","cwd":"P:/agentic-framework","scope":"plan-local checker pass/fail fixtures","phase":"targeted","result":"pass","exit_code":0,"tested_state":"b4398138871f19f3a5559343965bc4e1e8b5a4ede3675fa98d34e68376a33880","command":"python docs/execution/plans/2026-11-15-usb-kit-usability/check_kit.py --selftest","output":"selftest: 57 of 57 cases as expected","receipt_sha256":"46d057c0605a68a5fdb1b18cb9b16e0cdf91e289ed6238d8a3b80398a2d009b7"}
```

```json
{"schema_version":"evidence.v1","check_id":"review-pester-attempt","cwd":"P:/agentic-framework","scope":"Windows USB suite through required runner","phase":"targeted","result":"blocked","exit_code":1,"tested_state":"b4398138871f19f3a5559343965bc4e1e8b5a4ede3675fa98d34e68376a33880","command":"pwsh -NoProfile -File docs/execution/plans/2026-11-15-usb-kit-usability/run_pester.ps1 scripts/tests/SetupWindowsUsb.Tests.ps1","output":"SELF-CHECK FAILED: all passing gave False, expected True; same result after assigning TEMP and TMP to reviewer scratch. Suite did not run. Cause not established; not treated as a product regression.","receipt_sha256":"348ac62000ff3cbece8ede36ec990827cfdd0086246ce4f81ef5adf36f2a72ee"}
```

```json
{"schema_version":"evidence.v1","check_id":"review-reproductions","cwd":"P:/agentic-framework","scope":"F-001 through F-004","phase":"manual","result":"fail","exit_code":null,"tested_state":"b4398138871f19f3a5559343965bc4e1e8b5a4ede3675fa98d34e68376a33880","procedure":"Observed isolated scripted probes: load Windows library, substitute Test-Administrator and Start-Process in memory, supply a nonfinal child record containing every setup step and valid host-key data, invoke parent and validate its output with read_record. Separately instantiate the existing Kit/Prereq fixture with a preinstalled snap pwsh and no local link, run setup and an SSH-PATH lookup. Instantiate Rd with only the stub --config branch changed to exit 1. Call scan_lines with a synthetic link-local endpoint and a fixture deny pattern, without reading any real home or fleet record.","observer":"gpt-6.1-sol","output":"Windows: record rejected: unknown or repeated step 'elevate'. Snap: setup_exit=0, pwsh status=ok/detail=already installed, tools_has_pwsh=True, usr_local_pwsh_exists=False, ssh_path_pwsh_exit=1. Unix config: rustdesk_status=failed, detail=rustdesk --config failed, fallback_file_exists=False, restart_count=0. Synthetic link-local endpoint scan hits=[]. Each reproducer itself exited 0 after checking the observed defect."}
```

Probe receipt sha256 values: checkpoint `7796c78fe90fb4dc107036d635a2fc5112494faf1b3062e8a611682a6622bcc2`; snap `7226075f9a7a17c28d8a9dd096924925c5f6dd12834ef1fff44c546f7c1ec3a6`; config `c04967a4cd922d6f91f8503a5cacb65f3bde2d9cdef9f090e26446fe61ec015d`; privacy `28d95ca8c9a423bb03ce7367418ba0ada46f3e42c51dc32f961cc6a7c973c9e5`.

```json
{"schema_version":"evidence.v1","check_id":"review-evidence-binding","cwd":"P:/agentic-framework","scope":"handoff receipt hashes, red bodies, final state and regression baseline","phase":"manual","result":"pass","exit_code":null,"tested_state":"b4398138871f19f3a5559343965bc4e1e8b5a4ede3675fa98d34e68376a33880","procedure":"Parsed all handoff evidence.v1 JSON blocks and hashed their named receipts. Compared baseline/final failed ids and summaries and independently applied pytest_gate/red_check to receipt contents. Independently enumerated git diff paths plus untracked files, restricted to the explicit package paths, and hashed sorted path/content pairs plus git rev-parse HEAD, excluding task.md. Compared against check_kit --state and the handoff full gate.","observer":"gpt-6.1-sol","output":"50/50 evidence receipt hashes match; full-pytest secondary hash matches. All AC-1 through AC-21 have failing test bodies, with no refused setup/collection receipt. Independent identity matches: 17 paths, HEAD a73d6df2f327e977ca91d86a93c25c37fcfc2a7b. Baseline: 3 failed, 4873 passed, 1 skipped. Final: 3 failed, 5102 passed, 1 skipped. Both fail exactly the billing-line test and the two human-waived retained-credits tests. Package receipt: refcheck exit 1, sanitize exit 2, zero new failure lines; coverage every AC 1-21; privacy PASS. Author Pester: Passed=140, Failed=0, FailedBlocks=0, FailedContainers=0, Skipped=0, Uncovered=0."}
```

Hashes checked for the relied-on gates: baseline pytest `b8c018d7fd420d1ada7ca22027391457609c7cdc916c5c89b6160bd66a654645`; final pytest `45bedb069223dfd7689d25a208697356c12dcfac1093e0a7488bfe63f00c6409`; final pytest check `b044fb9c379422f8e45cd47b4c58879c386cc05eda6f37f595c56441f6314e90`; package gates `cb705111f6d40afa1ee30ae24fb929a936dadf5dfe0a2953ec136dab76130200`; Pester `aa8baf91f0ad3241efad8efd07e23e771db02c389cef051407d5a72f9a98248b`. Baseline package receipt reports 40 refcheck and 46 sanitize failure lines. The package gate found no additions; no existing failure is presented as newly introduced. The full suite was not rerun.

The handoff/check, AC-coverage, unchecked-task, MEU-skip, OpenAPI-skip and full-evidence receipts were inspected. Their decisive outputs are respectively: required sections and 26 AC rows present; all 26 ACs covered; no unchecked implementation row; the two no-op commands emitted nothing; durable evidence records OK. Empty no-op receipts alone are not evidence of a test run. The corresponding absence predicates and human blocks agree with the current files.

## Verdict

`changes_required` — fix F-001 and F-002 through `/execution-corrections`, run their focused regressions and the required affected gates, then submit round 2. F-003 and F-004 are non-blocking observations, not reasons to expand this into hardening work.

Remaining real-member risks are the actual package managers/installers, sudo-rs behavior, Windows GUI-subsystem CLI output and SSH quoting, RustDesk service/config/password behavior, launchd timing, network reachability, and macOS grants. Those require human rows 11a and 12-15; this review does not claim to resolve them. No implementation or authorization changes are requested beyond the supported findings.

🕐 Completed: 2026-11-15 20:35 (EST)

---

## Recheck (2026-11-15)

**Workflow:** `/execution-critical-review`. **Round:** 2 of 6. **Agent:** `gpt-6.1-sol` (dispatch registry). **Verdict:** `approved`.

**Intent anchor:** "Make the USB kit usable on every fleet member: members send their record to the hub over HTTP, the Ubuntu sudo-rs elevation chain works, the prerequisites install, and GUI members get RustDesk."

**Intent achieved:** yes for the implementation submitted to this review; the previously accepted real-machine human gates remain unrun.

### Prior Pass Summary

| Finding | Prior Status | Recheck Result |
|---|---|---|
| F-001, AC-2, blocking | open | Fixed: one failed `elevate` entry; final recovered record accepted by the hub reader. |
| F-002, AC-10, blocking | open | Fixed: a preinstalled snap receives the link used by the Account/SSH PATH. |
| F-003, AC-18, non-blocking | open | Fixed: nonzero config exit reaches read-back and TOML fallback. |
| F-004, non-blocking | open | Fixed: one synthetic link-local exemption; member record addresses enter class 5. |

### Scope

Independently reviewed the explicitly named corrections, new tests and surrounding branches; `task.md:136-138` (EA-14/15/16), the changed Privacy classes, and the rebuilt handoff's FAIL_TO_PASS, `r1fix-*` and H1 evidence. This is one correlated handoff with `meus: []`. Accepted round 1 decisions and unchanged implementation were not reopened. The earlier unrecorded round 2's conclusions were not used; its Recheck is replaced by this section. Round 1 is retained.

The original Findings table's four Status cells now say `fixed`, reflecting the verified closure in this recheck; the original findings, recommendations, evidence and round 1 verdict are retained. The closeout parser reads current statuses from that table.

The seventh known issue's content was excluded. EA-15 was checked only for the render repair: comparing the saved pre-render markdown with the current file shows exactly one changed totals line, and the current YAML/markdown pair passes `render --check`. EA-16 changes reporting text outside the tested code identity; the final package receipt covers the corrected text and reports zero new gate failures and no privacy hit.

### Confirmed Fixes and Test Rigor

- **F-001:** `.agent/fleet/usb/setup-windows.ps1:948-957` updates the existing step rather than appending its id. The new test at `scripts/tests/SetupWindowsUsb.Tests.ps1:201-219` checks final/failed state, exactly one `elevate`, retained successful `host_key`, and acceptance by actual Python `read_record`. **Strong.** Independently executed that exact test from an in-memory container with only the production branch restored: it failed with `Expected 1, but got 2`; corrected branch: one pass. No test assertion was changed. The unchanged USB suite also passes all 76 tests through the required runner.
- **F-002:** `.agent/fleet/usb/setup-unix.sh:495-501` links an existing snap before the generic installed-tool return. The new test at `scripts/tests/test_fleet_usb.py:928-939` starts with the snap and no link, asserts no redundant installation, and requires the exact executable symlink target plus successful `pwsh` step. **Strong.** The exact test fails with the original branch and passes with the correction in isolated fixture copies. The surrounding fresh snap/tarball, existing installation and rerun cases passed in the independent AC-10 subset.
- **F-003:** `.agent/fleet/usb/setup-unix.sh:985-1006` reports the config exit then retains the same read-back, fallback writes, restart, Ready wait and final id checks. The new test at `scripts/tests/test_fleet_usb.py:2477-2486` requires success, one config invocation, both configured folders, exactly one restart and the expected record id. **Strong.** The exact test fails with the original early-failure branch and passes with the correction. Linux and macOS readiness, missing config, bootstrap failure and restart cases passed in the independent AC-18 subset.
- **G36:** `scripts/tests/test_fleet_usb.py:2142-2147` preserves the stub's persistence side effect and changes only the selected config exit. Missing `config_exit` still yields 0; only the new test sets that file (`:2478`). Earlier assertions are not bypassed or relaxed. This is fixture setup, with a real failing regression test.
- **F-004:** `check_kit.py:388-400` exempts only the existing fixture address; `:459-461` adds string record addresses to deny terms. The Privacy contract agrees at `implementation-plan.md:291-303`. The new cases at `check_kit.py:896-906` are **Strong as a group**: IPv6 proves class 5 detection independently of class 1; the non-fixture IPv4 proves the narrowed allowance; fixture acceptance is a clean control. Reinstating both original behaviors produces the three new detection failures (58/61); corrections pass 61/61. The fourth new case is intentionally clean and passes in both states. All deny-term reads in reviewer probes used synthetic fixture homes/inboxes.

### Remaining Findings

None. No supported new regression or earlier unaccepted defect was found. F-001 through F-004 are closed; no additional correction is requested.

### Checklist Results

| Check | Result | Observation |
|---|---|---|
| IR-1 integration evidence | pass | Matching corrected full run retains the accepted integration coverage; no real-machine outcome is claimed. |
| IR-2 stub behavior / G36 | pass | Optional config exit preserves the original default and persistence; exact regression fails without the production fix. |
| IR-3 application error mapping | n/a | No application API route change in this focused review. |
| IR-4 generalization | pass | Checked snap fresh/existing paths and Windows/Unix config handling; both systems retain read-back behavior. |
| IR-5 test rigor | pass | Each new regression is Strong; supplementary privacy clean control is correctly distinguished from detection tests. Earlier accepted test grades remain unchanged. |
| IR-6 recovery boundaries | pass | Terminal checkpoint recovery goes through actual `read_record`; earlier checkpoint/cancel/final-record cases pass in the USB suite. |
| IR-7 coverage and deferrals | pass | All 26 AC rows remain present; human rows 11a and 12-15 retain named B blocks. MEU/API absence predicates agree with H1-3/H1-4 receipts. |
| DR-1 through DR-8, focused changes | pass | Corrected behavior and amendment claims agree; receipt hashes and independent input identity establish the full run; EA-15 render repair reproduced. |
| Independent unchanged sibling Pester repeat | n/a | Three unchanged AC-29 tests cannot construct scheduled-task objects in this sandbox (Access denied). The combined attempt was 138 passed/3 failed; this is not a passing full rerun. Matching author full Pester evidence is 141 passed/0 failed. |
| Real-machine deployment and current private-store scan | n/a | Explicitly excluded by this dispatch. No real home SSH store, credentials, hub or member was inspected/contacted. Historical full Privacy receipt and synthetic detection probes were checked. |

### Commands and Durable Observations

Reviewer probe scripts and raw outputs are under `C:/Temp/agentic-framework/receipts/dispatch/uk2-exec-review/`. The observations below include their decisive outputs. Probe mutations affected only temporary fixture copies or in-memory scriptblocks, never repository product files or tests.

```json
{
  "schema_version": "evidence.v1",
  "check_id": "r2b-windows-red-green",
  "cwd": "P:/agentic-framework",
  "scope": "EA-14/EA-15/EA-16 focused round 2",
  "phase": "targeted",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "e7f7aebec31e39733bf60c3b0fbd73b70f33a8d5ab2e70afd1b71af37bc97ef8",
  "command": "rtk proxy pwsh -NoProfile -File C:/Temp/agentic-framework/receipts/dispatch/uk2-exec-review/r2b-windows-probe.ps1",
  "output": "Exact new AC-2 test: original branch Passed=0 Failed=1, Expected 1 but got 2; corrected branch Passed=1 Failed=0. FailedBlocks=0 and FailedContainers=0 in both. Pester excludes the other tests in this isolated probe.",
  "receipt_sha256": "3ff0236cd230ceb3b5167e8fd15a773a6563f85f058e8714c367df96d72a9fb9"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "r2b-independent-mutations-and-state",
  "cwd": "P:/agentic-framework",
  "scope": "EA-14/EA-15/EA-16 focused round 2",
  "phase": "targeted",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "e7f7aebec31e39733bf60c3b0fbd73b70f33a8d5ab2e70afd1b71af37bc97ef8",
  "command": "rtk proxy python C:/Temp/agentic-framework/receipts/dispatch/uk2-exec-review/r2b-probes.py",
  "output": "F-002 and F-003: each exact new test fails with its original production branch and passes with its correction. F-004: original behaviors 58/61, corrected 61/61. Independent enumeration/hash of all 17 explicit tested inputs matches the handoff state.",
  "receipt_sha256": "15a43b665891295c0485ad0188f937d29a43dd11f5de5929913270d8d8681d03"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "r2b-targeted-regressions",
  "cwd": "P:/agentic-framework",
  "scope": "EA-14/EA-15/EA-16 focused round 2",
  "phase": "targeted",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "e7f7aebec31e39733bf60c3b0fbd73b70f33a8d5ab2e70afd1b71af37bc97ef8",
  "command": "python -m pytest scripts/tests/test_fleet_usb.py -q -rA -k \"ac10 or ac18 or ac21\" --basetemp=C:/Temp/agentic-framework/receipts/dispatch/uk2-exec-review/r2b-pytest-tmp",
  "output": "57 passed, 174 deselected, 1 warning in 596.10s (0:09:56)",
  "receipt_sha256": "7521c89a8624a0c7bf87400fae3c24c939fd42c61498b304500d21b245a0cf97"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "r2b-usb-pester",
  "cwd": "P:/agentic-framework",
  "scope": "EA-14/EA-15/EA-16 focused round 2",
  "phase": "targeted",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "e7f7aebec31e39733bf60c3b0fbd73b70f33a8d5ab2e70afd1b71af37bc97ef8",
  "command": "pwsh -NoProfile -Command '$env:TMP=$env:TEMP=\"C:/Temp/agentic-framework/receipts/dispatch/uk2-exec-review/r2b-tmp\"; $env:RECEIPTS_DIR=\"C:/Temp/agentic-framework/receipts\"; Import-Module Pester -MinimumVersion 5.0; $PesterPreference=New-PesterConfiguration; $PesterPreference.TestRegistry.Enabled=$false; & ./docs/execution/plans/2026-11-15-usb-kit-usability/run_pester.ps1 scripts/tests/SetupWindowsUsb.Tests.ps1'",
  "output": "Runner self-check passed. Pester gate PASS: Result=Passed Passed=76 Failed=0 FailedBlocks=0 FailedContainers=0 Skipped=0 Uncovered=0. TestRegistry disabled because sandbox refuses its registry key; this suite uses TestDrive and mocks system changes, with all assertions retained.",
  "receipt_sha256": "84813ee3a006c9fed1ee2baf3831b02ef8fa4d3cc096c7817d3b5fb41fe7204f"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "r2b-selftest",
  "cwd": "P:/agentic-framework",
  "scope": "EA-14/EA-15/EA-16 focused round 2",
  "phase": "targeted",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "e7f7aebec31e39733bf60c3b0fbd73b70f33a8d5ab2e70afd1b71af37bc97ef8",
  "command": "python docs/execution/plans/2026-11-15-usb-kit-usability/check_kit.py --selftest",
  "output": "selftest: 61 of 61 cases as expected",
  "receipt_sha256": "458b96ba70b7de8bea6efe933df82de01fb26ef0989d2c5e8073881e7c34f826"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "r2b-evidence-audit",
  "cwd": "P:/agentic-framework",
  "scope": "EA-14/EA-15/EA-16 focused round 2",
  "phase": "targeted",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "e7f7aebec31e39733bf60c3b0fbd73b70f33a8d5ab2e70afd1b71af37bc97ef8",
  "command": "rtk proxy python C:/Temp/agentic-framework/receipts/dispatch/uk2-exec-review/r2b-audit.py",
  "output": "58 handoff evidence records; 59/59 receipt hashes match, including the secondary full-pytest hash. Historical red bodies: one failure each for AC-2, AC-10, AC-18, no setup/discovery failures. Full pytest: exactly the three excused ids failed, 5104 passed, 1 skipped; gate PASS. EA-15 before/current comparison changes only the totals line.",
  "receipt_sha256": "31d447cac1615bfdaea9f7dca0074866f5bac310c3d764e233e54752002a8e5f"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "r2b-known-issues-render",
  "cwd": "P:/agentic-framework",
  "scope": "EA-14/EA-15/EA-16 focused round 2",
  "phase": "targeted",
  "result": "pass",
  "exit_code": 0,
  "tested_state": "e7f7aebec31e39733bf60c3b0fbd73b70f33a8d5ab2e70afd1b71af37bc97ef8",
  "command": "rtk proxy python core/tools/issue_triage.py --yaml .agent/context/known-issues.yaml --md .agent/context/known-issues.md render --check",
  "output": "OK: known-issues.md is up-to-date"
}
```

The initial pytest attempt used an unwritable default temp directory and did not exercise 54 fixture-based cases; it is superseded by the passing 57-test run above. The first Pester attempt used the requested temp override but stopped at its all-passing probe because Pester's default TestRegistry fixture cannot create its registry key. With that unused fixture disabled, the unchanged runner's fail/pass probes succeeded. The USB suite passed; the unchanged sibling's scheduled-task restrictions remain classified as unavailable independent evidence, not a new kit defect.

**Full-gate binding:** HEAD `a73d6df2f327e977ca91d86a93c25c37fcfc2a7b`, 17 changed inputs, state `e7f7aebec31e39733bf60c3b0fbd73b70f33a8d5ab2e70afd1b71af37bc97ef8`. Independently enumerated the named product, documentation, test and three non-task plan inputs and recomputed sorted path/content hashes. `check_kit.py --state` agrees. No full pytest rerun was performed.

Verified historical gate hashes:

| Receipt | SHA256 | Decisive observation |
|---|---|---|
| `uk2-full-pytest.txt` | `9e52d7df7a7821c4de21c9bfd33fcfca44f8135717a9d822b13e7dd0dfddc9c6` | 3 excused failed, 5104 passed, 1 skipped. |
| `uk2-full-pytest-check.txt` | `506f33c78fdf9a721caf28197b8850958bd214f7345395cc50a50eec8f43ecd8` | pytest gate PASS, raw pytest exit 1. |
| `uk2-pester.txt` | `f5a5a82e4a5bf61c9215199484e1d4ebde3ae81b02507ea7853532289de5335b` | 141 passed, no failed tests/blocks/containers, no skips/uncovered paths. |
| `uk2-package-gates.txt` | `febec1bcbf7203b6f47e10aff50706ea07772e3aabe1b3e821867e79cde7d481` | refcheck exit 1, sanitize exit 2, zero new baseline failures; AC-1 through AC-21 covered; Privacy PASS. |
| `uk2-state.txt` | `98c91a777eb7f70a47523d62c79f72ea96b705f42c10ad20a1f19eca16cddf0e` | Matches the independently recomputed corrected input identity. |

The `r1fix-*` hashes also all match. Their red pytest bodies show the missing snap link and `rustdesk --config failed`; red Pester shows the duplicate step. Red selftest has exactly the three new detection failures. The green package run's one AC-21 drift failure is the EA-15 event; its repair and three passing AC-21 tests agree with the independent run. H1-3 through H1-6b receipts were inspected: no unchecked implementation row; empty no-op receipts agree with actual absence predicates; all 26 AC rows present; durable full evidence valid. No empty receipt is treated as a test run.

### Verdict

`approved` — all four prior findings are fixed with discriminating regression evidence, and the focused checks found no new defect. No further implementation correction is required by this review. The dispatch copy is ready for the author to copy to `.agent/context/handoffs/2026-11-15-usb-kit-usability-implementation-critical-review.md` and submit to the ledger.

Real package installations/downloads, sudo-rs on fresh hardware, network reachability, RustDesk service/password behavior, SSH quoting and macOS permission grants remain the previously accepted human checks. No product, test, plan, work handoff or tool was edited; only this review and reviewer receipts/fixture probes were written. No credentials or real home stores were read, no member/hub contacted, no fleet task started, and no git commit or push was made.

🕐 Completed: 2026-11-15 22:53 (EST)
