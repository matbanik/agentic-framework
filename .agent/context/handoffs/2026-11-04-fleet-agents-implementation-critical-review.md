---
date: "2026-11-05"
review_mode: execution
target_plan: "docs/execution/plans/2026-11-04-fleet-agents/implementation-plan.md"
round: 3
verdict: approved
findings_count: 5
template_version: "2.2"
requested_verbosity: standard
agent: "gpt-6.1-sol"
---

# Critical Review: 2026-11-04-fleet-agents

> **Review Mode**: execution
> **Verdict**: approved

> The round 1 and round 2 assessments below are historical. All five finding statuses are now fixed; the current approved assessment is in the final round 3 Recheck.

## Scope

**Intent anchor:** "Let <hub host> start a Claude or Codex job on another machine with no sign-in there, talk to it while it runs, get its question back, resume it on Mat's words, and land its result on Mat's word, by connecting the credits engine and the dispatch wrappers to the fleet."

**Intent achieved:** partial. The recorded Claude and Codex jobs demonstrate the main round trips. Setup can corrupt an existing valid Codex configuration, so the delivered setup route is not ready for all of its supported inputs.

Reviewed the specified plan, task, single project handoff, tracked diff against HEAD `c9b47ca2336f78e2bdf511d8efd12de3709f5116`, new fleet files, named Python/Pester tests, and plan-local verifiers/helpers. The outline and MVP plan supply the ruled boundaries; they were not reopened. `meus: []` and the plan's Handoff Set identify one execution handoff. Applied IR-1 through IR-7 and DR-1 through DR-8 where relevant.

The author copies this dispatch artifact into the canonical repository handoff after dispatch. No product, test, plan, or existing handoff was edited. No production hub/member call, live verifier mode, fleet task, memory search, or commit was performed.

## Findings

| # | Severity | Blocking | Kind | Finding | File:Line | Recommendation | Status |
|---|----------|----------|------|---------|-----------|----------------|--------|
| F-001 | High | yes | behavior | **AC-3: setup turns a valid Codex configuration into invalid TOML.** An existing `[windows]` table with `sandbox = "unelevated"` is not recognized by the exact dotted-key regex. Setting `windows.sandbox` prepends `windows.sandbox = "unelevated"` above that table. The real function exits 0 and reports a change, but the resulting file fails parsing: `Cannot declare ('windows',) twice`. `Select-CodexSandbox` uses this writer, so subsequent CLI probes receive a broken configuration; a rerun does not remove the duplicate table. The existing preservation tests cover dotted keys and an unrelated table, missing this input. | `.agent/fleet/setup-member.ps1:65`; `.agent/fleet/setup-member.ps1:71`; `scripts/tests/SetupMember.Tests.ps1:90`; plan `implementation-plan.md:271` | Recognize the existing windows table when updating its sandbox key, preserve unrelated content, and cover a valid table-form input plus a second run with a TOML parse assertion. No general configuration-management layer is needed. | fixed |
| F-002 | Medium | no | behavior | **The live smoke helper bypasses the required commit identity.** `prepare` makes a real member-slot commit with explicit `user.name=fleet-smoke` and `user.email=fleet-smoke@fleet.invalid`. This is a live helper, not a synthetic test fixture, and does not use the checked identity carried by normal fleet snapshots. The human's every-repository identity rule still applies. The production AC-34/AC-41 snapshot paths do enforce their identity contract; this helper lies outside those particular chains, so this observation does not independently block them. | `docs/execution/plans/2026-11-04-fleet-agents/scripts/credits_smoke.py:150`; plan `implementation-plan.md:590` | Use <hub host>'s verified identity for the live smoke base instead of overriding it with the invalid identity. | fixed |
| F-003 | Medium | no | behavior | **A second test helper still leaks the bytecode flag fixed by A-18.** `real_receipt` imports the same probe modules in the pytest process and deletes their module entries, but never restores `sys.dont_write_bytecode`. An isolated invocation with fixture paths observed `False` before, `True` after, and `True` after `monkeypatch.undo()`. Both imported modules explicitly set the flag. This leaves later tests sensitive to ordering; the existing full run happens to run the affected core fixtures before this scripts helper. No product failure is inferred from this second leak. | `scripts/tests/test_fleet_agent.py:1408`; `core/.agent/skills/claude-credits/probes/kit.py:11`; `core/.agent/skills/claude-credits/probes/run_gate.py:49` | Restore the flag in this helper as in `load_probe`, without changing the unrelated fixture repositories. | fixed |
| F-004 | Low | no | clerical | **The saved package-gate pass does not describe the current handoff text.** A fresh comparison exits 1 with four differences: an existing remote-tool aggregate now has five sites and a different example, and the new bytecode-cache path in the handoff is unresolved, each reported by both gates. The 39/45 baseline counts are verified. These are handoff/reference changes, not demonstrated product regressions, and are non-blocking under the materiality gate. | `.agent/context/handoffs/2026-11-04-fleet-agents-handoff.md:943`; `.agent/context/handoffs/2026-11-04-fleet-agents-handoff.md:1066`; `docs/execution/plans/2026-11-04-fleet-agents/check_package_gates.py:95` | Correct the incidental reference text and refresh the package-gate receipt after the handoff's final edit; do not describe the current comparison as having no differences. | fixed |
| F-005 | High | yes | behavior | **AC-33 has no live proof for the changed Codex launch mode, although it remains marked complete.** P-4 changed the delivered direct-job path to FullAccess. Task H1-2 explicitly requires row 15 to repeat after a Codex change. The handoff says the only completed Codex job ran before P-4 and no job has used the new task path on a member. The full-access write probe bypasses fleet-tasks.ps1 and the dispatch wrapper; AC-40 exercises those components with a stub CLI. Together they support the change, but neither exercises the required live start, decision stop, same-session resume and final written file through the changed member path. This is a required integration acceptance gap, not a demonstrated code defect. Confidence: High. | plan implementation-plan.md:567; task.md:64; handoff:96,1318-1323,1348-1350; .agent/fleet/fleet-tasks.ps1:59-68,88; scripts/tests/test_fleet_agent.py:1960-1962,2045-2065 | Complete the existing bounded direct Codex row-15 start/decision/resume procedure on the installed P-4 kit, with Mat's actual start/resume words, and retain its real file, session, task and wrapper-mode evidence. Keep AC-33/H1-2 pending until that proof exists, or obtain an explicit human amendment accepting the composed evidence instead. No new control or runner is needed; preserve the already-proven unchanged D-5 route. | fixed |

F-001 is the sole blocker and violates **AC-3**. F-002 is about a deliverable helper; F-003 is committable test tooling; F-004 is handoff bookkeeping. No finding is classified as control-defeat and no mechanism id is invented.

### Decisive F-001 observation

Only a fixture under the dispatch receipts directory was used. The real setup function was dot-sourced with `-LibraryOnly`, then called with `-Key windows.sandbox -Value '"unelevated"'`.

```text
Before (valid, parsed by Python tomllib):
[windows]
sandbox = "unelevated"

PowerShell exit: 0
PowerShell output: True

After:
windows.sandbox = "unelevated"
[windows]
sandbox = "unelevated"

TOMLDecodeError: Cannot declare ('windows',) twice (at line 2, column 9)
```

This is an observed configuration-writing defect. Confirming Codex's exact runtime error on a member would require a member execution, which was not performed and is unnecessary to establish that setup wrote invalid TOML.

## Checklist Results

### Information Retrieval / Implementation Review

| Check | Result | Command or procedure | Exit | Evidence |
|-------|--------|----------------------|------|----------|
| IR-1 live runtime evidence | pass | Read all five live modes, associated JSON records, live helper source and result diffs; verify handoff receipt hashes | n/a, manual | Historical runs have real S4U/model evidence and the expected decisions/results; no reviewer live run |
| IR-2 stub behavioral compliance | pass | Inspect shim configuration, call logs, store exports, filesystem checks and real-wrapper AC-40 tests | n/a, manual | Separate tests cover forwarding, real wrappers, negative routes and live integration |
| IR-3 HTTP error mapping | n/a | This is a fleet protocol, not the API-route mapping described by IR-3 | n/a | Relevant fleet refusal codes and zero-row behavior are covered under AC-17 to AC-20 |
| IR-4 correction generalization | partial | Inspect A-16/A-17/A-18 and search both in-process probe loaders | n/a, manual | Named AC-11 correction holds; F-003 finds a second flag leak |
| IR-5 test rigor | partial | Read every new test and changed fleet test, including assertion helpers and mutation receipts | n/a, manual | Ratings below; F-001 is an uncovered layout and F-003 is an isolation defect |
| IR-6 boundaries | partial | Inspect schema/manifest, hub validation, config writer, result checks and targeted tests | n/a, manual | Closed envelopes and result checks hold; config boundary fails F-001 |
| IR-7 AC coverage and deferrals | pass | Compare all 41 plan ACs with handoff rows and named tests/live procedures | n/a, manual | No silently dropped AC; ruled limits remain explicit |
| Independent targeted pytest | pass | `rtk proxy python -X utf8 -m pytest core/tools/tests/test_credits_fleet_gate.py scripts/tests/test_fleet_agent.py -q -rfE -p no:cacheprovider -k "ac11 or ac18 or ac19 or ac20 or ac26 or ac30 or ac32 or ac35 or ac36" --basetemp C:/Temp/agentic-framework/receipts/dispatch/fleet-agents-exec-review/pytest-confirmed` | 0 | **113 passed, 178 deselected in 73.88s** |
| Independent AC-11 pytest | pass | `rtk proxy python -X utf8 -m pytest core/tools/tests/test_credits_fleet_gate.py -q -rfE -p no:cacheprovider --basetemp C:/Temp/agentic-framework/receipts/dispatch/fleet-agents-exec-review/ac11-temp` | 0 | **11 passed in 0.28s** |
| Live verifier negative predicates | pass | `rtk proxy python docs/execution/plans/2026-11-04-fleet-agents/check_live.py --selftest` | 0 | **28 of 28 ok**, including bad session, no reply, no file, missing denial and wrong result identity |
| Pester rerun | partial | `rtk proxy pwsh -NoProfile -NonInteractive -File docs/execution/plans/2026-11-04-fleet-agents/run_pester.ps1 scripts/tests/SetupMember.Tests.ps1` | 1 | Runner's passing self-check cannot run because the sandbox denies Pester's HKCU Software/Pester registry access; no suite result claimed |
| Full-gate state | pass | Compute HEAD + porcelain + `sys.version` identity; run `durable_evidence.py ... --require-full --expected-state d6f21b1515d19bda6e869fd376a3239c8ac2c1b8b0e5eaaf2e24d0177d6e35ac` | 0 | `OK: durable evidence records`; matches the verified full receipt, **4643 passed, 1 skipped, 36 subtests passed** |

All reviewer test commands used `RECEIPTS_DIR=C:/Temp/agentic-framework/receipts`. The pytest selections avoid the installed fixture that hashes the real home Claude settings. The full suite was not rerun.

### AC assessment

| ACs | Assessment and independently inspected basis |
|-----|---------------------------------------------|
| AC-1, AC-2 | Source/AST and publication checks have deliberate bad-copy cases; member kit stays stdlib-only and capability reporting adds pwsh |
| AC-3 | **Fails F-001** for a valid table-form Codex config; installer/idempotence tests otherwise have real call-count and byte assertions |
| AC-4, AC-5 | Write-test selection and one elevated try are implemented; historical twice-run setup passes for the delivered <member host> layout. This does not cover F-001's other valid layout |
| AC-6 to AC-10, AC-12, AC-13 | Schema, auth routes, S4U definitions, token-hash/env capture, no-key negative cases, real launcher/dispatch calls and same-session resume covered by CreditsFleetMember Pester source and verified staged receipts |
| AC-11 | Current gate-project checks preserve CLI, kit and hook-profile checks; 11 independent tests pass |
| AC-14, AC-15 | Kit build/verify/swap, retained runs, hook merge, gate scrub, leak cleanup and redaction have positive/negative fixture tests; no real home settings were opened by this reviewer |
| AC-16 | S4U run, acknowledged info delivery, budget argv and qualifying gate are in the raw JSON; P-3 rules the billing proof |
| AC-17 to AC-20 | Hub sender/quote/body/tool validation occurs before append; HTTP negative tests assert exact errors and zero added rows |
| AC-21 to AC-27 | Registration/start ordering, exact quote, normalized real exports, retained receipt check, secret withholding and watch exits inspected. Targeted AC-26 test confirms the member survives and completes a following fixture ping |
| AC-28 | Historical query answered while state is running, decision/watch 7, `hold south` resume, same session/slot, final done; landed diff contains south |
| AC-29 to AC-32 | Fixed workspace wrapper mode/class, resume forwarding, total status mapping, lock lifetime/recursive refusal/override refusal and two allowed wrapper rules covered by fixture tests and mutation receipts |
| AC-33 | Historical Codex decision/resume has equal session ids, files draft/answer=west, status DONE; remote Claude has a Codex dispatch and a FullAccess denial |
| AC-34 to AC-36, AC-41 | Production snapshot identity matches global noreply config, overridden environment cannot replace it, result identity/tree/hash checks and zero-old-value ref update preserve branches/HEAD/index; refusal tests exercise real git repositories. F-002 is outside these production chains |
| AC-37 | Both recorded result refs have matching trees/author/committer and unchanged branch lists; result diffs are south/west, landing quote matches Mat's words, drop outcomes recorded |
| AC-38 | Required three human stops, unchanged billing rule, member skill sections and manifest entries covered. Clean-machine bootstrap sequencing limitation noted below |
| AC-39 | Coverage map holds, but the **current package comparison fails** on handoff-reference drift (F-004) |
| AC-40 | Real instantiated wrappers accept member briefs/slots and fixed class, reject outside roots/missing bindings, and preserve the review-class resume refusal; assertions are behavioral |

### Live checker judgment

`check_live.py` is a receipt interpreter, not an independent live observer. Its required negative predicates genuinely fail. Its limitations do not invalidate the actual supplied runs:

- **setup**, lines 53-94: checks report fields, both writes, second changed list, sandbox, member binding, registry hash prefix and capabilities. S4U provenance comes from the real setup script and its receipt.
- **credits**, lines 97-128: checks DONE/auth/S4U/ack/budget/gate and P-3's quote/window substitute. It does not itself require `is_using_overage == false`; the actual JSON records false. P-3 explicitly removes the meter-movement requirement.
- **agent**, lines 131-158: checks quote refusal, quotes, reply, decision/watch, same session/slot and done. It does not validate query timing; the actual JSON has `query_reply_run_state: running`, and `live_agent.py` records that state from status polling.
- **codex**, lines 161-177: checks file/status, resumed-between-turns and answer/denial. It does not independently validate workspace mode or equal session ids; the task script fixes the mode, the real-wrapper tests inspect sandbox argv, and the actual receipt supplies equal session ids and west in the written file.
- **result**, lines 180-210: checks both CLIs, refs/trees/identity, diff/drop flags, branches and landing word. Diff presentation is an operator attestation, not something this script can observe. The supplied landing words are expressly authorized, and the diff artifacts exist with the expected contents.

No machinery is requested to turn those procedural observations into automated enforcement.

### Test rigor and red evidence

Every pytest `test_*` function and Pester `It` case in the new files was inspected, including their shared assertion helpers. Each is rated **Strong** unless listed as Adequate below; parameterized instances inherit their case's rating. Changed legacy tests retain meaningful assertions. No test was rated Weak merely because a fixture or helper contains the actual assertion.

| Test scope | Rating and limitation |
|------------|-----------------------|
| `test_fleet_agent.py`, 179 test functions | Strong by default: real HTTP/member fixtures, exact argv and values, git round trips and negative side effects. Adequate: `test_ac01_a_member_hello_reports_pwsh` (key presence), `test_ac40_the_kit_holds_the_task_script` (existence), and AC-38 prose/manifest presence checks. F-003 affects helper isolation, not assertion strength |
| `test_credits_fleet_gate.py`, 11 functions | Strong: exact clean verdict, changed CLI/hooks/settings/project cases, and real command-line dispatch. `load_probe` now restores the flag |
| `SetupMember.Tests.ps1`, all AC-2/3/4/29 cases | Strong for fixtures, bytes, call counts, sandbox file contents, task principal/actions, option forwarding, case-sensitive status and removal. Mandatory-parameter metadata and source-presence checks are Adequate. Missing table-form config coverage is F-001 |
| `CreditsFleetMember.Tests.ps1`, all cases | Strong for launcher/store/wrapper/environment/resume/classifier/export behavior. Registration-only exit cases and unchanged-default metadata checks are Adequate; no catch-and-ignore oracle |
| `CodexDispatchFleetLock.Tests.ps1`, all cases | Strong: real competing wrapper processes, nested call, exact busy exit, stub count, refusal ordering, release and unset-variable behavior |
| Legacy hub/bootstrap/run tests | Strong by default; source/template presence checks and successful-call-only assertions are Adequate. Removed old disabled-agent test is correctly replaced by AC-17; run identity fixtures use isolated global config |

Every FAIL_TO_PASS row has an inspected nonempty red receipt with failed assertions, blocks or containers. Early missing-implementation failures are correctly labeled as such, rather than being presented as individual mutation proofs. AC-1's early missing-manifest skip is explained and covered later. The final suite and targeted receipts show its implemented state.

The AC-29 mutation receipt kills **27/27** changes: script removal; S4U/task path/start/Force/action; task and wrapper resume; class/mode/non-review flag; model/effort/timeout; queued state and status-line order/case/anchor; task result; stop/remove; run-name/action validation; host publication and required brief. The restored suite passes **59** tests. The AC-31 receipt kills **7/7** changes: shared handle, busy exit/text, removed/late executable refusal, unconditional lock and early release; restored exit 0. AC-26's oracle removes the secret catch and demonstrates the member termination. These receipts' hashes match the handoff.

### Decisions and controls

- **P-3 stands.** The supplied human ruling is verbatim in the receipt. Stream data says no API key source, a subscription window and overage false. Nobody demonstrated meter movement or reread the Console afterwards; those are acknowledged limits, not a reopened decision.
- **A-16 holds.** `setup-member.ps1:92` no longer passes a model flag, and fixtures use fake slugs. The probe's account-default cost remains bounded by its existing cap. No evidence that this choice widens job permissions.
- **A-17 holds.** Hash-verified `fa-setup-rerun.log` records two post-change runs, both write tests passing, changed empty, and the final setup check at zero problems. Original reports remain separate. The approved row-3 authorization covers the rerun.
- **A-18 holds for the named AC-11 correction and subsequent full run**, not as a claim that every probe import is now isolated. `load_probe` uses monkeypatch to restore the incoming flag. Red/fixed receipts show 2 failed + 11 passed becoming 13 passed; both prior full failures and the later 4643-pass full receipt match their stated hashes. F-003 identifies the remaining second loader.
- **Secrets:** fleet envelopes use the existing scanner; job text is withheld after a secret refusal without ending the member; launch-hook token/env tests have meaningful positive/negative assertions. No real credential was read here. Filesystem access by a process running as the member user remains the ruled boundary.
- **Permissions and recursion:** the production Claude manifest fixes acceptEdits; fleet Codex fixes ReviewWorkspace; the exclusive file handle spans dispatch lifetime and executable override is refused before acquisition. Broad user-approved Python tools and bare nested Codex inside a sandbox remain declared limitations, not new findings.
- **Authority/results:** start/resume quotes are required and retained exactly; neither the quote nor result CLI proves chat provenance mechanically. Mat's supplied words authorize the reviewed runs/results. Result landing changes a non-branch ref, not HEAD or a branch. Production noreply checks hold; F-002 records the helper exception.
- **Scope/simplicity:** the shipped code connects existing credits/dispatch paths through the existing fleet transport. No second general runner or unsolicited enrollment/credential system was added. The extra local research/smoke options are isolated helper code; their additional author-recorded quotes are not treated as independently verified chat history.

### Evidence auditability / freshness

All **49 handoff evidence-record SHA-256 values** match files in the allowed receipt folder, including every red row, A-17, A-18, staged gates and the final full gate. The empty skip receipts hash correctly; they are not evidence of product behavior. The live text receipts contain only `0 problem(s)`, so the JSON and helper/code review above are necessary additional evidence, not implied by those text hashes.

The independently recomputed D6 identity is `d6f21b1515d19bda6e869fd376a3239c8ac2c1b8b0e5eaaf2e24d0177d6e35ac`, matching the full record. It binds HEAD, porcelain paths and Python version, **not dirty-file contents**; this limits what the freshness check establishes. The verified full receipt reports `4643 passed, 1 skipped, 67 warnings, 36 subtests passed in 3125.54s`. Existing staged receipts report 393 Pester passes, 59 setup passes, and 526 staged credits pytest passes. These are historical observations, not reviewer reruns.

The baseline JSON is bound to HEAD c9b47ca and contains refcheck 39/sanitize 45. Its saved text and final package receipt hashes match. Independently running the current comparison yields four differences, so **the assertion that none is new cannot be confirmed for the present handoff** (F-004). Two differences are changed aggregations of an existing tool failure; two are a new unresolved handoff reference. No new executable product defect is inferred from them.

Reviewer outputs under `C:/Temp/agentic-framework/receipts/dispatch/` include `fleet-agents-review-pytest.txt`, `fleet-agents-ac11-pytest.txt`, `fleet-agents-live-selftest.txt`, `fleet-agents-config-probe.txt`, `fleet-agents-bytecode-probe.txt`, `fleet-agents-package-gates.txt`, `fleet-agents-full-evidence.txt`, `fleet-agents-receipt-audit.json`, `fleet-agents-setup-pester.txt`, and `fleet-agents-pester-environment.txt`. The decisive observations are pasted here rather than delegated solely to those paths.

```json
{"schema_version":"evidence.v1","check_id":"review-targeted-pytest","cwd":"P:/agentic-framework","scope":"AC-11,18,19,20,26,30,32,35,36","phase":"targeted","result":"pass","exit_code":0,"tested_state":"HEAD c9b47ca plus reviewed working tree","command":"rtk proxy python -X utf8 -m pytest core/tools/tests/test_credits_fleet_gate.py scripts/tests/test_fleet_agent.py -q -rfE -p no:cacheprovider -k \"ac11 or ac18 or ac19 or ac20 or ac26 or ac30 or ac32 or ac35 or ac36\" --basetemp C:/Temp/agentic-framework/receipts/dispatch/fleet-agents-exec-review/pytest-confirmed","output":"113 passed, 178 deselected in 73.88s; captured child exit 0"}
```

```json
{"schema_version":"evidence.v1","check_id":"review-live-selftest","cwd":"P:/agentic-framework","scope":"all five live receipt interpreters, offline only","phase":"targeted","result":"pass","exit_code":0,"tested_state":"reviewed working tree","command":"rtk proxy python docs/execution/plans/2026-11-04-fleet-agents/check_live.py --selftest","output":"selftest: 28 of 28 ok"}
```

```json
{"schema_version":"evidence.v1","check_id":"review-config-writer","cwd":"P:/agentic-framework","scope":"AC-3 valid table-form Codex config","phase":"targeted","result":"fail","exit_code":null,"tested_state":"reviewed setup-member.ps1","procedure":"Reviewer created a fixture containing [windows] and sandbox=unelevated, confirmed it parses with tomllib, invoked the actual Set-CodexConfigLine through pwsh -NoProfile -NonInteractive after dot-sourcing setup-member.ps1 -LibraryOnly, then parsed the resulting fixture again.","observer":"gpt-6.1-sol","output":"Function exit 0, output True; added windows.sandbox before existing [windows]; tomllib: Cannot declare ('windows',) twice (at line 2, column 9)."}
```

```json
{"schema_version":"evidence.v1","check_id":"review-package-gates","cwd":"P:/agentic-framework","scope":"AC-39 current versus row-0 baseline","phase":"static","result":"fail","exit_code":1,"tested_state":"reviewed working tree and current handoff","command":"rtk proxy python docs/execution/plans/2026-11-04-fleet-agents/check_package_gates.py","output":"4 problem(s) against baseline head c9b47ca: existing remote tool aggregate changes from 4 sites to 5, plus unresolved bytecode-cache handoff reference, each reported by refcheck and sanitize."}
```

### Out-of-Contract Observations

- Clean-machine bootstrap ordering needs clarification: `.agent/fleet/bootstrap.md:30` requires setup/write checks before browser sign-in at line 68, but `setup-member.ps1:153` fails Claude's write test without the token; document the prerequisite or the intended install/sign-in/recheck sequence without adding a new runner.

### Residual risk

The acknowledged collect-then-resume/drop risk is confirmed by `fleet.py:2043` and `:2050`: collection is a marker, and resume does not invalidate it. AC-36 requires prior collection and inactivity, not proof that the marker describes the latest slot; no new freshness machinery is demanded. Collect again after resumed work before dropping it.

The logout probe records token revocation after the live rows, and the relogin probe records restored subscription access. This does not retroactively invalidate their receipts and is not proof of current member state. Future login refresh, CLI updates, sandbox behavior and task-scheduler behavior require member execution to recertify; none was performed here.

## Verdict

**changes_required** — fix F-001's configuration corruption and add the missing table-form regression before approval. F-002 through F-004 are non-blocking corrections. Route implementation fixes through `/execution-corrections`; this review applies none. Re-run affected checks and the plan's required final gates after input-changing corrections, preserving the existing human boundaries for any necessary live retest.


## Recheck (2026-11-05)

**Workflow:** execution-critical-review, round **2 of 6**.  
**Agent:** gpt-6.1-sol (the live dispatch registry's independent_reviewer binding on codex-cli).  
**Verdict:** **changes_required**.  
**Intent anchor:** "Let <hub host> start a Claude or Codex job on another machine with no sign-in there, talk to it while it runs, get its question back, resume it on Mat's words, and land its result on Mat's word, by connecting the credits engine and the dispatch wrappers to the fleet."

**Intent achieved: partial.** The historical jobs prove the main round trips, and all four prior findings are fixed. The changed direct Codex route still lacks its required member round trip under FullAccess (F-005). This is an uncompleted runtime acceptance check, not an observed failure of FullAccess or a challenge to P-4.

### Prior Pass Summary

| Finding | Prior Status | Recheck Result |
|---|---|---|
| F-001, High / AC-3 | open, blocking | **Fixed.** The actual writer recognizes the windows table, limits replacement to its section, and inserts a missing key there. Four independent fixture probes pass parsing and second-call idempotence. |
| F-002, Medium | open, non-blocking | **Fixed.** The smoke helper receives <hub host>'s identity through smoke.json and uses it for its commit. |
| F-003, Medium | open, non-blocking | **Fixed.** real_receipt registers the incoming bytecode flag with monkeypatch; teardown restores it. The new regression passes independently. |
| F-004, Low | open, non-blocking | **Fixed.** The handoff reference drift is removed; the current package comparison exits 0 with no new failure. |

### Remaining Findings

| # | Severity | Blocking | Kind | Finding | File:Line | Recommendation | Status |
|---|---|---|---|---|---|---|---|
| F-005 | High | yes | behavior | **AC-33 has no live proof for the changed Codex launch mode, although it remains marked complete.** P-4 changed the delivered direct-job path to FullAccess. Task H1-2 explicitly requires row 15 to repeat after a Codex change. The handoff says the only completed Codex job ran before P-4 and no job has used the new task path on a member. The full-access write probe bypasses fleet-tasks.ps1 and the dispatch wrapper; AC-40 exercises those components with a stub CLI. Together they support the change, but neither exercises the required live start, decision stop, same-session resume and final written file through the changed member path. This is a required integration acceptance gap, not a demonstrated code defect. Confidence: High. | plan implementation-plan.md:567; task.md:64; handoff:96,1318-1323,1348-1350; .agent/fleet/fleet-tasks.ps1:59-68,88; scripts/tests/test_fleet_agent.py:1960-1962,2045-2065 | Complete the existing bounded direct Codex row-15 start/decision/resume procedure on the installed P-4 kit, with Mat's actual start/resume words, and retain its real file, session, task and wrapper-mode evidence. Keep AC-33/H1-2 pending until that proof exists, or obtain an explicit human amendment accepting the composed evidence instead. No new control or runner is needed; preserve the already-proven unchanged D-5 route. | fixed |

**Violated contract:** AC-33. **Subject:** deliverable. No control-defeat mechanism is assigned. The missing member run is expressly disclosed, so this finding does not accuse the author of concealing it. Disclosure does not amend the plan's live acceptance requirement.

### Confirmed Fixes and P-4 Boundaries

- **F-001:** .agent/fleet/setup-member.ps1:67-88 confines the update to the existing table or the top-level section. scripts/tests/SetupMember.Tests.ps1:104-140 covers replacement, insertion, a final header without a newline, and twice-run setup, including parser and byte assertions. The saved red receipt has four relevant assertion/parser failures with the old writer; it is not an unrelated Pester startup failure. The current standalone probes exercise replacement, insertion, final-header and dotted-key layouts: all parse, all have the expected value, and all return false on the second identical write. This closes the original mutation class without demanding a general TOML editor.
- **F-002:** scripts/run_credits_smoke.py:42-48,57-58 checks <hub host>'s global name/address for presence and the noreply suffix and carries them in smoke.json. scripts/credits_smoke.py:150-152 uses that supplied identity instead of fleet-smoke@fleet.invalid. These are the scripts under this plan folder. No helper was run on a member during review.
- **F-003:** scripts/tests/test_fleet_agent.py:1407-1408 records the incoming flag before imports; :1454-1464 checks it after the monkeypatch context closes. The red receipt shows the exact True-is-False assertion, and the current regression passes. The helper restores at fixture teardown, consistent with load_probe; it does not claim that the flag is unchanged during its own import.
- **F-004:** the fresh check_package_gates.py comparison returns exactly "0 problem(s) against baseline head c9b47ca", exit 0. The baseline JSON records HEAD c9b47ca2336f78e2bdf511d8efd12de3709f5116 and 39 refcheck / 45 sanitize failure lines. The saved baseline text and current package receipt match their handoff hashes. No new normalized failure line, missing manifest entry or missing AC test is reported.

**P-4 is faithfully implemented in the reviewed source.** .agent/fleet/fleet-tasks.ps1:29-30,59-68 fixes FullAccess and its P-4 justification for both direct starts and resumes. The justification satisfies the wrapper's existing non-whitespace length check (core/tools/Invoke-CodexDispatch.ps1:950-960); that validation was not weakened. The wrapper maps FullAccess to danger-full-access at :1173-1176 and sends it with -s at :1231. The saved AC-40 run passes nine cases through the installed task script and real wrapper with a stub CLI; its start assertion at scripts/tests/test_fleet_agent.py:2052-2053 checks the resulting sandbox argument.

The write-scope text reaches both start and resume briefs: .agent/fleet/fleet.py:1920-1943 defines and places CODEX_WRITE_SCOPE before the job; :1983 and :2022 use that builder. fleet-tasks.ps1:62 forwards the brief as PromptFile, and the wrapper copies it into its prompt at core/tools/Invoke-CodexDispatch.ps1:1207-1212. The new AC-29 test checks the literal scope and its order before the job (scripts/tests/test_fleet_agent.py:1670-1676). The scope is an instruction, not filesystem enforcement, exactly as P-4 rules.

**No wider permission change was found in these paths.** Claude's generated launch still uses acceptEdits (.agent/fleet/fleet.py:1731), and allow_codex_rules still creates only ReviewReadOnly and ReviewWorkspace (:1718-1720). AC-32 checks the exact two rules and absence of FullAccess (scripts/tests/test_fleet_agent.py:1885-1902); those cases pass in the independent run. The global wrapper mode mapping and FullAccess check are unchanged by this work. Setup's separately authorized full-access probe is the other FullAccess use: setup-member.ps1:165-168,247-262 makes it decide codex, while codex_sandbox records the sandbox outcome. A sandbox failure alone no longer fails setup.

The active bootstrap instructions and cli-dispatch fleet section describe FullAccess and the sign-in prerequisite (.agent/fleet/bootstrap.md:30-37; core/.agent/skills/cli-dispatch/SKILL.md:489-496). The old D-4 decision text and the outline preserve the pre-P-4 ruling. Plan implementation-plan.md:131-137 still phrases the read/recursive-call risks in terms of unelevated / "inside its sandbox"; read those historical sentences with P-4's explicit no-sandbox limit at :1075-1082. They do not change the actual mode.

### Evidence and Decision Assessment

**All 62 handoff evidence-record SHA-256 values match the corresponding retained receipt bytes.** This includes F-001 and F-003 red, P-4 red-gate and green runs, A-17/A-18, the current H1-2 stages, and the full suite. Empty skip receipts and shared "0 problem(s)" text are not treated as proof of the underlying live facts; the JSON records and their producer code were also inspected.

| Evidence / decision | Judgment |
|---|---|
| A-16 | **Holds.** setup-member.ps1:109 has the existing budget cap and no model pin; the tests use fake models. The account-default model affects cost, not permissions. |
| A-17 | **Holds for its historical claim.** The hash-matched retained log records two post-A-16 setup passes, empty changed lists and a passing setup check. Later sandbox failures supersede its reliability as evidence of today's sandbox, which the corrections now explain. |
| A-18 | **Holds.** test_credits_fleet_gate.py:22-30 restores the flag via monkeypatch. The matched red receipt records the two named main_dirty fixture failures (2 failed, 11 passed), followed by 13 passed with the fix. F-003 closes the second helper's leak. The current full receipt records 4645 passed. |
| A-19 / AC-5 | **Holds for the setup rerun.** Both current report JSONs have changed empty, reason null, Claude pass, Codex pass and codex_sandbox fail. The matched rerun log records two setup exits 0; the separate matched setup-check receipt says 0 problems. run_member_setup.py:64-76 transfers the actual script and saves the member's report. Setup's S4U path is setup-member.ps1:121-136. This proves setup, not AC-33. |
| Full-access diagnosis and probe | The probe receipt records done=True, probe=True, passed=True, 44 expected bytes, and a successful pwsh write. This supports the specific capability workaround. Its short tail does not independently prove the stronger universal statement that every prior sandbox invocation failed; no such universal claim is needed to honor P-4. |
| AC-16 | The recorded S4U credits run has DONE, inherited auth, an acknowledged info delivery, budget argv, a qualifying gate, and acceptEdits. P-3's exact human quote and the token stream's no-key source / subscription window / overage false are present. The meter did not move and the Console was not reread; P-3 stands. |
| AC-28 | The recorded query reply arrived with query_reply_run_state running. Start and resume have the same session and slot, watch stopped with exit 7 and decision, the exact resume quote is hold south, then DONE. live_agent.py:128-145 records the timing state from polling. The result diff holds south. |
| AC-33 | The historical workspace-write run has draft.txt, answer.txt=west, decision stop and matching resumed session IDs. The remote Claude job got a Codex answer and its FullAccess attempt was denied. This remains valid history for the unchanged portions, not a post-P-4 member-job proof: **F-005**. |
| AC-37 | The saved landing word equals the supplied human words. Read-only git inspection independently confirms both local result refs, trees, and MatBanik noreply author/committer identities; diffs contain south and west respectively. Saved before/after branches match and drop outcomes are recorded. Diff presentation and chat authority remain procedural observations, not mechanically authenticated by check_live.py. |

**Fresh full-gate evidence:** independent computation of HEAD + porcelain output + sys.version gives 412529387e58b632f5745dd05d6f5d60306edaff04e0e987766894528e4e2504, matching the handoff's final H1-2 record. durable_evidence.py --require-full --expected-state returns exit 0, "OK: durable evidence records". The hash-matched full receipt says **4645 passed, 1 skipped, 67 warnings, 36 subtests passed in 3110.20s**. The run log records all seven H1-2 stages exiting 0. The saved stage receipts show 590 targeted pytest passes, 65 setup Pester passes, 393 staged Pester passes and 526 staged credits pytest passes. These are author runs, not reviewer reruns. The D6 identity binds paths, not dirty-file contents; this previously disclosed limitation remains.

### Checklist Results

| Check | Result | Executed command or manual procedure | Exit | Decisive observation |
|---|---|---|---|---|
| IR-1 / IR-7 live acceptance | fail | Manual: compare plan AC-33, task H1-2, the live JSON producer and handoff points 14 / Deferred Items; observer gpt-6.1-sol | null | No post-P-4 member Codex job; F-005 |
| IR-2 / IR-4 / IR-5 / IR-6 corrections and boundaries | pass | Manual: inspect the corrected writer, receipt helper, smoke identity, new AC-3/P-4/AC-25/AC-29/AC-40 assertions, exact allowed modes, lock and identity call chains; observer gpt-6.1-sol | null | Prior findings fixed; meaningful positive/negative assertions and matching red receipts |
| Independent targeted pytest | partial | rtk proxy python -X utf8 -m pytest core/tools/tests/test_credits_fleet_gate.py scripts/tests/test_fleet_agent.py -q -rfE -p no:cacheprovider -k "ac11 or ac18 or ac19 or ac20 or ac25 or ac26 or ac29 or ac30 or ac32 or ac40" --basetemp C:/Temp/agentic-framework/receipts/dispatch/fleet-agents-exec-review/r2-targeted-temp | 1 | **124 passed, 160 deselected, 9 errors**; all nine errors share AC-40 fixture setup's denied access to core/.pytest_cache, before its assertions |
| Isolated correction / mode tests | pass | rtk proxy python -X utf8 -m pytest scripts/tests/test_fleet_agent.py -q -rfE -p no:cacheprovider -k "bytecode_flag or ac29_the_brief_keeps or ac32" --basetemp C:/Temp/agentic-framework/receipts/dispatch/fleet-agents-exec-review/r2-isolated-temp | 0 | **7 passed, 275 deselected** |
| Independent F-001 probe | pass | Manual procedure executed by Python: create four TOML fixtures in the dispatch folder, dot-source actual setup-member.ps1 -LibraryOnly in pwsh, invoke the actual writer twice per fixture, require [true,false], parse with tomllib and check the sandbox value; observer gpt-6.1-sol | null | **4/4 pass**: replace, insert, final header, dotted key |
| Pester reviewer attempt | partial | rtk proxy pwsh -NoProfile -NonInteractive -File docs/execution/plans/2026-11-04-fleet-agents/run_pester.ps1 scripts/tests/SetupMember.Tests.ps1 | 1 | SELF-CHECK FAILED: all passing gave False, expected True. The requested suite did not run; no reviewer Pester pass claimed |
| Offline live-check selftest | pass | rtk proxy python docs/execution/plans/2026-11-04-fleet-agents/check_live.py --selftest | 0 | **28 of 28 ok** |
| Baseline comparison / AC-39 | pass | rtk proxy python docs/execution/plans/2026-11-04-fleet-agents/check_package_gates.py | 0 | **0 problem(s) against baseline head c9b47ca** |
| Full-gate identity | pass | Independently compute task H1-6b identity, then invoke rtk proxy python core/tools/durable_evidence.py .agent/context/handoffs/2026-11-04-fleet-agents-handoff.md --require-full --expected-state 412529387e58b632f5745dd05d6f5d60306edaff04e0e987766894528e4e2504 | 0 | OK: durable evidence records; saved full gate hash matches |
| DR claim/state and scope | partial | Manual: compare tracked diff against c9b47ca and read the explicitly named untracked source, plan-local scripts and corrected handoff; observer gpt-6.1-sol | null | Corrections and P-4 source claims hold; current completion claim for AC-33 exceeds the evidence |
| IR-3 route-specific HTTP mappings | n/a | The workflow's application HTTP error-mapping rubric does not apply; fleet refusal behavior is covered under its own ACs | n/a | Existing AC-18/19 refusal assertions pass |

Test rigor: the new/revised AC-3, P-4, AC-25 flag and AC-29 scope cases are **Strong**: they assert bytes, parser results, call arguments, exact failure reasons, exit decisions, teardown state or actual generated brief text. AC-40's revised mode assertion is **Strong** for the real task-script/wrapper/stub integration and is explicitly insufficient as a live-member oracle. AC-11's eleven cases and the inspected lock suite retain concrete rejection, value and side-effect assertions. Round 1's remaining test ratings are retained for unchanged cases; no new Weak test was found in the corrections. The four F-001 red failures, F-003 True-is-False failure and five P-4 behavior failures demonstrate relevant failing assertions rather than import/discovery errors.

The live checker remains a receipt interpreter: setup_problems checks the two primary writes but not codex_sandbox; credits_problems does not itself enforce overage=false; agent_problems does not independently enforce query timing; codex_problems checks neither effective mode nor equal session IDs; result_problems trusts the diff_shown attestation. The supplied raw records cover these historical facts where stated. In particular, codex_problems cannot turn a historical receipt into current FullAccess proof. No new verification machinery is requested.

### Controls, Scope and Residual Risks

The review found no correction that bypasses the secret scanner, changes Claude's D-4 mode, relaxes the quote rule, changes result landing into a branch operation, weakens noreply checks, or removes FLEET_CODEX_LOCK. Exact source anchors: .agent/fleet/fleet.py:564-595 (quotes/body), :1731-1751 (Claude launch), :1173-1225 and :2034-2053 (identity/snapshot), :1412-1437 (result validation/ref); core/tools/Invoke-CodexDispatch.ps1:557-568 (exclusive lock and executable refusal). The current targeted run exercises the quote/body, secret-withholding and exact AC-32 boundaries. No credential content was read. Broad allowed Python tools, user-readable sign-in files, bare nested CLI calls outside the wrapper's lock and collect-then-resume-then-drop remain declared trust-boundary limits, not newly escalated findings.

P-4 accepts instruction-only write scope on the owner's own machines; this review does not request a replacement sandbox, identity service, enrollment route or additional runner. The remaining **member-only runtime uncertainty** is whether the real changed task/wrapper/CLI path completes start and resume with its expected files/session on <member host>. Only a member job can settle it; none was run here. F-005 tracks the explicit AC-33 requirement for that proof.

No live mode, hub request, <member host> contact, fleet task, memory search, commit or source edit was performed. The installed-fixture tests that hash real home settings were excluded. Local result repositories were read only, using command-scoped safe.directory entries without changing global Git configuration. Only dispatch review/evidence files were written.

### Durable Reviewer Observations

```json
{"schema_version":"evidence.v1","check_id":"r2-targeted-pytest","cwd":"P:/agentic-framework","scope":"AC-11,18,19,20,25,26,29,30,32,40","phase":"targeted","result":"blocked","exit_code":1,"tested_state":"HEAD c9b47ca plus reviewed working tree","command":"rtk proxy python -X utf8 -m pytest core/tools/tests/test_credits_fleet_gate.py scripts/tests/test_fleet_agent.py -q -rfE -p no:cacheprovider -k \"ac11 or ac18 or ac19 or ac20 or ac25 or ac26 or ac29 or ac30 or ac32 or ac40\" --basetemp C:/Temp/agentic-framework/receipts/dispatch/fleet-agents-exec-review/r2-targeted-temp","output":"124 passed, 160 deselected, 9 errors in 99.79s. Nine AC-40 fixture errors: shutil.copytree cannot read core/.pytest_cache (WinError 5); none reached an assertion."}
```

```json
{"schema_version":"evidence.v1","check_id":"r2-correction-pytest","cwd":"P:/agentic-framework","scope":"F-003, P-4 brief scope, AC-32","phase":"targeted","result":"pass","exit_code":0,"tested_state":"HEAD c9b47ca plus reviewed working tree","command":"rtk proxy python -X utf8 -m pytest scripts/tests/test_fleet_agent.py -q -rfE -p no:cacheprovider -k \"bytecode_flag or ac29_the_brief_keeps or ac32\" --basetemp C:/Temp/agentic-framework/receipts/dispatch/fleet-agents-exec-review/r2-isolated-temp","output":"7 passed, 275 deselected in 9.11s"}
```

```json
{"schema_version":"evidence.v1","check_id":"r2-package-gates","cwd":"P:/agentic-framework","scope":"AC-39 current versus row-0 baseline","phase":"static","result":"pass","exit_code":0,"tested_state":"HEAD c9b47ca plus reviewed working tree","command":"rtk proxy python docs/execution/plans/2026-11-04-fleet-agents/check_package_gates.py","output":"0 problem(s) against baseline head c9b47ca; baseline JSON contains 39 refcheck and 45 sanitize failure lines."}
```

```json
{"schema_version":"evidence.v1","check_id":"r2-live-selftest","cwd":"P:/agentic-framework","scope":"five offline live receipt interpreters","phase":"targeted","result":"pass","exit_code":0,"tested_state":"HEAD c9b47ca plus reviewed working tree","command":"rtk proxy python docs/execution/plans/2026-11-04-fleet-agents/check_live.py --selftest","output":"selftest: 28 of 28 ok"}
```

### Verdict

**changes_required** — F-001 through F-004 are fixed. F-005 is the sole blocker, against AC-33: complete the required post-P-4 member job proof or obtain an explicit human amendment to that acceptance requirement. Route any corrections through /execution-corrections. This review applies no fixes and authorizes no live run.

🕐 Completed: 2026-11-05 21:04 (EST)

## Recheck (2026-11-05)

**Workflow:** `/execution-critical-review`, round **3 of 6**.  
**Agent:** `gpt-6.1-sol`, verified against the dispatch registry's `independent_reviewer` / `codex-cli` binding.  
**Verdict:** **approved**.  
**Intent anchor:** "Let <hub host> start a Claude or Codex job on another machine with no sign-in there, talk to it while it runs, get its question back, resume it on Mat's words, and land its result on Mat's word, by connecting the credits engine and the dispatch wrappers to the fleet."

**Intent achieved: yes**, within the human's D-1 to D-6 and P-1 to P-4 boundaries. F-005's missing live acceptance evidence now exists. The review does not authorize a further job, landing, cleanup, commit or push.

### Prior Pass Summary / Current Findings

| Finding | Severity | Blocking now | Kind | Prior status | Round 3 result and evidence | Status |
|---|---|---|---|---|---|---|
| F-001 / AC-3 | High | no | behavior | fixed | **Still fixed.** The actual writer updates the existing windows section and is idempotent. Four fresh fixture probes parse with tomllib and return True then False. Source: `.agent/fleet/setup-member.ps1:67-91`; parser/byte regressions: `scripts/tests/SetupMember.Tests.ps1:104-140`. Hash-matched red has four relevant failures; saved green has 65 passes. | fixed |
| F-002 | Medium | no | behavior | fixed | **Still fixed.** `scripts/run_credits_smoke.py:42-48,57-58` carries <hub host>'s checked noreply identity; `scripts/credits_smoke.py:150-152` commits with it. These paths are relative to this plan folder. No fixed smoke identity remains on this route. | fixed |
| F-003 | Medium | no | behavior | fixed | **Still fixed.** `scripts/tests/test_fleet_agent.py:1407-1408` registers the incoming bytecode flag for restoration; `:1454-1464` checks it after teardown. The regression passed in the fresh targeted run. The matched red shows `assert True is False`, rather than a collection error. | fixed |
| F-004 | Low | no | clerical | fixed | **Still fixed.** A fresh `check_package_gates.py` run exits 0: `0 problem(s) against baseline head c9b47ca`. Handoff corrections at `:1317-1323` match the current text and saved package receipt. | fixed |
| F-005 / AC-33 | High | no | behavior | open, blocking | **Fixed.** `fa-row15p4` runs after kit install/gate, stops for a decision, resumes on `west` in the same session and slot, writes the expected answer, and ends DONE. Both wrapper turns record FullAccess / danger-full-access / exit 0. Source: plan-local `scripts/live_codex.py:142-168,182-208`; observations: `fa-live-codex.log:22-31`, `fa-live-codex.json:2-11,40-68`; handoff `:1354-1365`. | fixed |

**Remaining findings: none.** Historical descriptions and verdicts above are retained as the record of what each round knew. All five findings are now fixed; the historical Blocking cells describe their severity when raised.

### Scope and Verification

Re-read the specified single handoff and its AC/evidence/decision tables, the plan and task, the outline's ruled boundaries, the relevant MVP contracts, all tracked changes against HEAD `c9b47ca2336f78e2bdf511d8efd12de3709f5116`, and the explicitly named untracked fleet sources, tests, verifiers and plan-local helpers. Plan `implementation-plan.md:45-53` declares one project handoff and `meus: []`; no extra MEU closeout is inferred. D-13/D-15 local files are intentional. The explicit dispatch output path overrides the workflow's in-repository write location; the author copies this rolling artifact back afterwards.

**F-005 evidence cross-check:** the current JSON and original log agree on the exact start quote `Run row 15 again (Recommended)`, resume quote `west`, dispatches `fa-row15p4-1` and `fa-row15p4-2`, and slot. The first watch exits **7**, asking east or west with `STOPPED:decision`; the second exits **0**, with `DONE`. Both session IDs are `01a1aea5-d9a0-7291-b9e2-97846d881464`. A separate recorded member read returns `draft.txt = draft ok`, `answer.txt = west`. The log's final read returns each turn's real wrapper receipt fields; its PowerShell JSON preserves those strings under `value`, and the current evidence normalizes them to strings. `live_codex.py:193-200` now explicitly casts each line to string. Neither the normalization nor a watch exit alone is used as the success oracle.

The kit-install and kit-gate log bytes match the blob hashes in the recorded fleet wait results, and the latter says **GATE live PASS: 5/5; qualifying=true**. Read-only `git show` comparison against install snapshot `a06f18dc047f00325591c6f93e9f67fbc85a7df5` found **26/26 named code/test inputs identical** to the current source after CRLF normalization. Install and gate report the same source tree `fe717e19adbd1cde286117dd3aed8f4e43626843`. This ties the observed FullAccess run to the reviewed P-4 implementation, rather than relying only on the author's prose.

The retained `remote_claude` object equals the pre-P-4 record exactly. It shows a real Codex dispatch ending 0, the returned answer file, and a FullAccess attempt in `permission_denials` with `This command requires approval`. Keeping that unchanged D-5 proof is valid: P-4 changes the direct Codex task, not Claude's allow rules. The new result was not landed; the unchanged AC-37 route is already evidenced by the original two results, and no new landing word was supplied.

### P-4 and Control Assessment

- **Scope of FullAccess:** `.agent/fleet/fleet-tasks.ps1:29-30,59-68` fixes the mode and P-4 justification for a direct Codex start/resume. The justification satisfies the unchanged wrapper check at `core/tools/Invoke-CodexDispatch.ps1:950-960`. The real-wrapper AC-40 test asserts the resulting `-s danger-full-access`, actual session and resume argv (`scripts/tests/test_fleet_agent.py:2045-2065`); its matched saved run has **9 passes**. AC-29's Pester assertions check the task definition, class, mode, justification and forwarding (`scripts/tests/SetupMember.Tests.ps1:314-369`).
- **The brief reaches the job:** `.agent/fleet/fleet.py:1921-1943` places the literal `CODEX_WRITE_SCOPE` before the job; `:1983` and `:2022` use the same builder for start/resume. The task passes it as PromptFile (`fleet-tasks.ps1:62`), which the wrapper reads into its prompt (`Invoke-CodexDispatch.ps1:1207-1212`). AC-29's fresh integration case checks the literal scope and its ordering (`test_fleet_agent.py:1670-1676`). This is instruction-only write scope, exactly as ruled.
- **No expansion to Claude:** `fleet.py:1731` remains `acceptEdits`; `allow_codex_rules` at `:1718-1720` still yields exactly ReviewReadOnly and ReviewWorkspace. Fresh AC-32 cases verify both exact rules and no FullAccess (`test_fleet_agent.py:1879-1915`). The subscription launch hook removes both Anthropic key variables and supplies only the token/scrub to the child (`core/.agent/skills/claude-credits/Invoke-ClaudeCredits.ps1:374-384`). No new credential route is introduced.
- **Other controls hold:** the exclusive wrapper lock and executable override refusal remain at `Invoke-CodexDispatch.ps1:557-568`; Claude's launcher env gets the same lock path (`member_kit.py:186-187`). The quote/body checks still precede task append (`fleet.py:564-595,623-642`); fresh quote/body and secret-withholding tests pass. Snapshot identity is still checked against global noreply config and pinned into all four commit variables (`fleet.py:1173-1225`); result validation uses the zero-old-value non-branch ref update (`:1412-1437`). Landing on Mat's word remains the declared procedural boundary, not an invented authentication service.
- **Setup is amended as ruled:** `setup-member.ps1:165-168,247-265` makes FullAccess decide `codex`, preserving `codex_sandbox` separately. The hash-matched probe supports a successful 44-byte full-access pwsh write under S4U; it does not independently prove the universal historical claim that every sandboxed invocation failed. Setup reruns and the new real task/wrapper/CLI round trip support the actual workaround. No replacement sandbox or runner is needed.

Active bootstrap step 1 (`.agent/fleet/bootstrap.md:30-36`) and the cli-dispatch fleet section (`core/.agent/skills/cli-dispatch/SKILL.md:491-498`) describe FullAccess and its limitation. The outline D-4 and older decision/risk sentences retain workspace-write/unelevated wording. Those are the pre-P-4 ruling/history, explicitly amended by plan `:256-258,518-521,563,567,1075-1082`; they are not evidence that the current direct job is sandboxed. The unchanged Claude-to-Codex path intentionally remains sandboxed.

### Live ACs and Author Decisions

| Item | Judgment and observed basis |
|---|---|
| A-16 | **Holds.** The setup Claude probe has a budget and no model pin (`setup-member.ps1:109`). Changing fake fixture models satisfies the package gate without loosening it. Using the account default changes probe cost, not its write oracle. |
| A-17 | **Holds historically.** The retained, hash-matched `fa-setup-rerun.a17.log` contains two exit-0 setups, empty changed lists and a passing setup check. Later sandbox failures supersede any claim of reliable sandbox writes; they do not erase the earlier observations. |
| A-18 | **Holds.** `test_credits_fleet_gate.py:22-30` restores the import flag. The matched red records the two `main_dirty` fixture failures with 11 passes; the fix gives 13 passes, and the later full gate passes. F-003's second loader is also fixed. The fresh AC-11 cases pass. |
| A-19 / AC-5 | **Holds.** Both current setup reports have `changed=[]`, reason null, Claude pass, Codex pass and codex_sandbox fail; the matched rerun log has two setup exits 0. The saved setup check says 0 problems. `run_member_setup.py:64-76` transfers the real script and saves the returned report; `setup-member.ps1:121-136` defines the S4U probe. Setup's full-access write is separate from the now-completed job acceptance proof. |
| AC-16 | **Holds under P-3.** The raw credits record has S4U, DONE, acknowledged info delivery, budget argv, qualifying gate and acceptEdits. P-3's actual words accompany a no-key subscription window and overage=false. No meter movement or reread Console balance is inferred. |
| AC-28 | **Holds.** The raw JSON records the query reply while running, decision/watch 7, `hold south`, equal session/slot and final DONE. The helper records query timing from status (`scripts/live_agent.py:128-145`), and the local landed answer is south. |
| AC-33 | **Holds after P-4.** The new FullAccess start/decision/resume/file evidence closes F-005; the unchanged remote Claude record proves D-5's answer/denial path. |
| AC-37 | **Holds for the original landed runs.** Fresh read-only local Git checks confirm both result refs, expected trees, MatBanik noreply author/committer, answer files south/west and unchanged branch lists. The saved landing word exactly matches Mat's supplied words. Drop outcomes and diff presentation remain recorded procedural observations; no member state was queried. |

`check_live.py` remains a receipt interpreter. Its offline selftest passes **28/28**. The setup mode would query the hub and was not run. The actual data was checked beyond its predicates: codex_problems (`:145-160`) does not itself check mode/session equality, credits_problems does not enforce overage=false, agent_problems does not enforce reply timing, and result_problems trusts `diff_shown`. Those facts were verified directly where recorded; the checker is not represented as a stronger control.

### Checklist Results and Test Rigor

| Check | Result | Executed command or manual procedure | Exit | Decisive observation |
|---|---|---|---|---|
| IR-1 / IR-7 live acceptance | pass | Manual: compare current/pre-P-4 JSON, logged tasks, helper producer and source install snapshot; observer gpt-6.1-sol | null | AC-33's changed member path now has an actual start/decision/resume round trip with files and mode evidence. All 41 ACs remain in the handoff. |
| IR-2 / IR-4 / IR-5 / IR-6 | pass | Manual: inspect every named test's assertions and helpers, the config correction, P-4 forwarding, closed bodies, lock, secret and identity routes; observer gpt-6.1-sol | null | Meaningful positive/negative behavior; no new Weak test or material product false-pass established. |
| Targeted pytest | pass | `rtk proxy python -X utf8 -m pytest core/tools/tests/test_credits_fleet_gate.py scripts/tests/test_fleet_agent.py -q -rfE -p no:cacheprovider -k "ac11 or ac18 or ac19 or ac20 or ac25 or ac26 or ac29 or ac30 or ac32" --basetemp C:/Temp/agentic-framework/receipts/dispatch/fleet-agents-exec-review/r3-targeted-temp` | 0 | **124 passed, 169 deselected in 106.06s**. |
| Actual config writer | pass | `rtk proxy python -X utf8 C:/Temp/agentic-framework/receipts/dispatch/fleet-agents-exec-review/r3_probes.py` | 0 | **4/4** layouts parse and are idempotent; **26/26** code/test inputs match the post-P-4 install snapshot. |
| Live evidence/local results cross-check | pass | `rtk proxy python -X utf8 C:/Temp/agentic-framework/receipts/dispatch/fleet-agents-exec-review/r3_results.py` | 0 | Quotes/session/slot/files/modes match; original result refs/trees/identities/answers/branches match. |
| Pester reviewer rerun | blocked | `rtk proxy pwsh -NoProfile -NonInteractive -File docs/execution/plans/2026-11-04-fleet-agents/run_pester.ps1 scripts/tests/SetupMember.Tests.ps1` | 1 | `SELF-CHECK FAILED: all passing gave False, expected True`. The requested suite did not execute; no fresh Pester pass claimed. |
| Offline live-check selftest | pass | `rtk proxy python -X utf8 docs/execution/plans/2026-11-04-fleet-agents/check_live.py --selftest` | 0 | **selftest: 28 of 28 ok**. |
| AC-39 / baseline comparison | pass | `rtk proxy python -X utf8 docs/execution/plans/2026-11-04-fleet-agents/check_package_gates.py` | 0 | **0 problem(s) against baseline head c9b47ca**. Row-0 JSON contains 39 refcheck / 45 sanitize failure lines; the baseline text hash matches the handoff. No new normalized failure was found. |
| Receipt hashes/full-state verification | pass | `rtk proxy python -X utf8 C:/Temp/agentic-framework/receipts/dispatch/fleet-agents-exec-review/r3_audit.py` | 0 | **63 evidence-record hashes matched, 0 unmatched**; independently computed D6 state matches; durable_evidence exits 0. |
| AC table | pass | `rtk proxy python -X utf8 core/tools/validate_closeout_artifacts.py --plan docs/execution/plans/2026-11-04-fleet-agents/implementation-plan.md --handoff .agent/context/handoffs/2026-11-04-fleet-agents-handoff.md --ac-coverage-only` | 0 | **OK: all 41 plan AC(s) present in the handoff**. |
| DR-1 through DR-8 | pass | Manual: compare code/diffs, current handoff claims, changed live record, stated limits and saved/fresh gate outputs; observer gpt-6.1-sol | null | Corrected completion claim is supported; historical modes remain identified; no new scope expansion. |
| IR-3 application-route error mapping | n/a | Not an application route implementation; the relevant fleet refusal codes and zero-row effects have integration tests | n/a | No API mapping requirement is imported. |

Every test function/case in the named new files was audited, including shared assertion helpers. Ratings apply to each case, including parameterized instances: **Strong by default**, with **Adequate** for AC-1 capability presence, AC-38 prose/manifest presence, AC-40 task-file existence, setup mandatory-parameter metadata, and credits registration-only/default-metadata checks. AC-3/P-4 cases assert bytes, parser results, task arguments and opposite exit decisions; AC-25 asserts teardown state; AC-31 uses real competing wrapper processes and exact call counts; AC-40 uses installed real wrappers with stub CLIs. Result refusal helpers assert no new commit/blob and unchanged slot state. No new Weak case was found. Existing unchanged legacy-case ratings above stand. Tests that hash actual home settings were not executed.

The required red receipts were checked by bytes and by their failed assertions: F-001 **4 failed / 59 passed** with the old writer; F-003 **1 failed** at the flag restoration assertion; P-4 **5 failed / 60 passed**, covering wrong sandbox, wrong setup outcomes, wrong wrapper mode and absent justification. Their matching green runs support the specific corrections. The current H1-2 receipts report **590 targeted pytest**, **65 setup Pester**, **393 staged Pester**, **526 staged credits pytest**, and full **4645 passed, 1 skipped, 67 warnings, 36 subtests passed in 3110.20s**. The run log records all seven stages exiting 0. These saved Pester/full results are author runs, not reviewer reruns.

**Full-gate identity:** independently computed HEAD + porcelain + sys.version is `412529387e58b632f5745dd05d6f5d60306edaff04e0e987766894528e4e2504`. `durable_evidence.py --require-full --expected-state` returns `OK: durable evidence records`, exit 0. The full receipt hash is `ab38d6b4f9701263fcda7265f57725b9d9b71922c0b5ee5b243bea8730b18264`. The disclosed D6 identity binds paths, not dirty-file contents; it is not described as a content attestation. The separately inspected source snapshot and reviewer input hashes add direct checks for this review. The full suite was not rerun.

Selected independently computed raw evidence hashes, retained to identify precisely what this round read:

| Receipt | SHA-256 |
|---|---|
| fa-live-codex.json | aa8703407d4877c99bed3110857a498f4d33a74e3965f1067553f7aedf9cee11 |
| fa-live-codex.prep4.json | 6e360ff0b244213661620de16fc8de15a2a2cc3e436c0682c4184623a1f96d39 |
| fa-live-codex.log | f94bfc2dea090c9e9f479f73dbda0f2ffbe1cf556b96237e4adf9f3e8c28a66f |
| fa-row15-kit-install.log | 4a2139475d4ffdcad9cd1ce15d70c75c64c7b328608cbc85b8205ea2501e8e73 |
| fa-row15-kit-gate.log | f493c3894dcb0dccdfc2aa94d29b73d8e481d12af126285023c592f21e863322 |
| fa-setup-report-1.json and fa-setup-report-2.json | 985edeaf435c25c40ae9616c00f1a5e76fa5f84a9ac75f9ac2fc67a55602222f |

### Durable Reviewer Observations

```json
{"schema_version":"evidence.v1","check_id":"r3-targeted-pytest","cwd":"P:/agentic-framework","scope":"AC-11,18,19,20,25,26,29,30,32","phase":"targeted","result":"pass","exit_code":0,"tested_state":"412529387e58b632f5745dd05d6f5d60306edaff04e0e987766894528e4e2504","command":"rtk proxy python -X utf8 -m pytest core/tools/tests/test_credits_fleet_gate.py scripts/tests/test_fleet_agent.py -q -rfE -p no:cacheprovider -k \"ac11 or ac18 or ac19 or ac20 or ac25 or ac26 or ac29 or ac30 or ac32\" --basetemp C:/Temp/agentic-framework/receipts/dispatch/fleet-agents-exec-review/r3-targeted-temp","output":"124 passed, 169 deselected in 106.06s (0:01:46)"}
```

```json
{"schema_version":"evidence.v1","check_id":"r3-package-gates","cwd":"P:/agentic-framework","scope":"AC-39 current versus row-0 baseline","phase":"static","result":"pass","exit_code":0,"tested_state":"412529387e58b632f5745dd05d6f5d60306edaff04e0e987766894528e4e2504","command":"rtk proxy python -X utf8 docs/execution/plans/2026-11-04-fleet-agents/check_package_gates.py","output":"0 problem(s) against baseline head c9b47ca"}
```

```json
{"schema_version":"evidence.v1","check_id":"r3-live-selftest","cwd":"P:/agentic-framework","scope":"offline live-receipt negative predicates","phase":"targeted","result":"pass","exit_code":0,"tested_state":"412529387e58b632f5745dd05d6f5d60306edaff04e0e987766894528e4e2504","command":"rtk proxy python -X utf8 docs/execution/plans/2026-11-04-fleet-agents/check_live.py --selftest","output":"selftest: 28 of 28 ok"}
```

```json
{"schema_version":"evidence.v1","check_id":"r3-pester-attempt","cwd":"P:/agentic-framework","scope":"SetupMember Pester reviewer rerun","phase":"targeted","result":"blocked","exit_code":1,"tested_state":"412529387e58b632f5745dd05d6f5d60306edaff04e0e987766894528e4e2504","command":"rtk proxy pwsh -NoProfile -NonInteractive -File docs/execution/plans/2026-11-04-fleet-agents/run_pester.ps1 scripts/tests/SetupMember.Tests.ps1","output":"SELF-CHECK FAILED: all passing gave False, expected True. Requested suite did not execute."}
```

### Residual Risks / Follow-up / Verdict

The accepted limits remain: instruction-only Codex write scope and user-readable sign-in files (P-4 / handoff points 15-16); broad allowed Python commands and bare nested CLI calls beyond the wrapper lock (plan `:131-139`); and collect-then-resume/drop relying on operator order (`fleet.py:2016-2025,2043-2069`). Recollect changed work before dropping it. The old served bootstrap text remains until a hub restart (handoff `:1347-1350`), without invalidating the corrected source instructions. None is reopened as a new blocker.

**Member-only runtime risk:** future login refresh, CLI updates and S4U behavior on a different or changed member need execution there to recertify. Saved evidence proves the recorded <member host> runs, not present/future member health or indefinite reliability. The earlier F-005 uncertainty about the P-4 member round trip is now settled by that recorded run. No member execution was performed during this review.

**approved** — no remaining evidence-backed blocker or new correction note. F-001 through F-005 are fixed. No extra machinery, product correction or additional live run is requested. The author may copy this rolling review to its canonical repository path and perform the separately governed closeout steps; this reviewer has not performed them. No product/test/plan/handoff-under-review edit, memory search, credential read, hub call, <member host> contact, fleet task or commit occurred. All reviewer writes are under the authorized dispatch receipts directory.


🕐 Completed: 2026-11-05 22:38 (EST)
