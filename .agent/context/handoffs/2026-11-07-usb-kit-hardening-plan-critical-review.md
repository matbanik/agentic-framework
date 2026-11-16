---
date: "2026-11-14"
review_mode: "plan"
target_plan: "docs/execution/plans/2026-11-07-usb-kit-hardening"
verdict: "approved"
findings_count: 0
review_round: 10
review_round_cap: 10
template_version: "2.2"
requested_verbosity: "detailed"
agent: "Codex"
---

# Critical Review: 2026-11-07-usb-kit-hardening

> **Review Mode**: `plan`
> **Verdict**: `changes_required`
> **Round**: 1 of 3

Executing this plan should close the seven stated kit findings while preserving a working admin connection, limiting privileged operations and network exposure, verifying downloads, and producing usable tests and public documentation. It does not yet deliver that objective: the supported counterexamples below survive the source and peer-plan cross-checks.

## Scope

**Target**: `docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md` and `docs/execution/plans/2026-11-07-usb-kit-hardening/task.md`, read in full.

**Review type**: unstarted plan review, using PR-1 through PR-9 and applicable DR-1 through DR-8 from `core/.agent/workflows/plan-critical-review.md`.

Reviewed all work packages, AC-1 through AC-25 (including both AC-14 halves), every task row, every Named definition, D-1/D-2, A-1 through A-17, the exclusions and stop conditions. Compared the committed kit at `28f76e0` and `f8ce76e`, the current source and the four separately owned dirty-file diffs; also read the named manifest, update checklist, bootstrap and both READMEs. The peer plan's gate/checker and Pester runner were inspected directly.

Threat model: accidents and real attackers against members. The human's plan-to-execution reading is the trust anchor. No finding alleges implementer-authored checks or forged author evidence. D-1 and D-2 remain human decisions; this review selects neither.

No kit, fleet, test, plan or documentation file was changed. No live member, hub, SSH host, installer/setup command, credential file or signing operation was used by the review. Existing tests used their own local fixtures; external reads were public documentation/source references only.

## Findings

| # | Severity | Blocking | Kind | Finding | File:Line | Recommendation | Status |
|---|----------|----------|------|---------|-----------|----------------|--------|
| F-001 | High | yes | behavior | **Confidence: Medium.** D-1 A constrains argv and PATH but leaves the package-manager environment unconstrained. On a member whose existing sudo policy preserves APT_CONFIG, an attacker with the hub key can select an agent-writable APT configuration containing a root pre-invoke hook, then invoke the allowed helper with an ordinary package name. This is a root-command route outside the stated repository-package residual risk (PR-4, PR-8). | `docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:308; :314-318; :127-129; :940-946` | Specify and test a clean allowlisted environment for privileged child commands, pin a trusted system PATH, and address interpreter startup environment before claiming the package-only residual. Include a poisoned APT_CONFIG negative case; document any required sudo-policy precondition. | open |
| F-002 | High | yes | behavior | **Confidence: High.** The password-off checks prove syntax and two password settings, without establishing that the installed hub key can authenticate. An existing valid PubkeyAuthentication no configuration passes the stated checks; both Unix and Windows then disable password authentication and leave the hub unable to sign in. The later import only discovers the lockout (PR-4, PR-8; Goal finding 3 and A-12). | `docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:394-411; :422; :454-458; :472; :877-881` | Make working key authentication a prerequisite for password-off, with a reversible confirmation step or equivalent effective-config checks and rollback until the hub key is confirmed. Test a valid password-only SSH configuration on both paths. | open |
| F-003 | High | yes | behavior | **Confidence: High.** A failed Unix rerun removes the drop-in even when a previous successful run installed it. With a pre-existing valid password-off drop-in, a failed candidate/check destroys the previous protection; macOS applies the missing drop-in on the next connection, and Linux loses it on a later reload or reboot. AC-16 explicitly requires this destructive failure behavior (PR-4, DR-4; finding 3). | `docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:409-411; :431; :917-921` | Snapshot the old drop-in bytes, ownership and mode; restore them on failure, removing the candidate only when no previous file existed. Test both first-run and rerun failures, and validate restored configuration before any reload. | open |
| F-004 | High | yes | behavior | **Confidence: High.** The firewalld recipe makes the rich rules permanent but specifies --remove-service=ssh followed by --reload without making the removal permanent. Following those argv literally removes only the runtime service; reload reinstates the permanent unrestricted SSH service, defeating the subnet limit (PR-4, DR-4; finding 3). | `docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:404-406; :430; docs/execution/plans/2026-11-07-usb-kit-hardening/task.md:49` | Specify zone-scoped permanent removal explicitly, reconcile this standard-service change with A-4, and assert both runtime and permanent state after reload and a repeat run. | open |
| F-005 | High | yes | behavior | **Confidence: High.** The first-start firewalld path tries to enumerate active zones and configure permanent rules before starting the daemon, using firewall-cmd. That client requires a running daemon. A member with firewalld installed but stopped cannot reach the promised safe first enable; no offline configuration branch/tool is planned (PR-4; WP-U5 and A-11). | `docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:397-406; :175-177; :430; :867-871` | Define a stopped-daemon branch using offline configuration with explicit target zones, validate it, then perform the listener guard and start. Add stubs that return NOT_RUNNING for daemon-client calls until start, rather than canned success. | open |
| F-006 | High | yes | behavior | **Confidence: High.** WP-U4 only manages OpenSSH-Server-In-TCP. No Windows task or assertion enumerates and reports a differently named broader inbound SSH rule. With a second enabled broad rule, the canonical rule and AC-23 can look correct while SSH remains reachable through the broader rule without the A-4 warning (PR-8; finding 2 and A-4). | `docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:117; :358-375; :630; docs/execution/plans/2026-11-07-usb-kit-hardening/task.md:48; .agent/fleet/usb/setup-windows.ps1:72-83` | Add Windows effective-rule enumeration and reporting for other enabled inbound allows covering SSH, including broad profile/address/port matches. Preserve those rules as A-4 requires and test a canonical rule beside a broader second rule. | open |
| F-007 | High | yes | control-defeat | mechanism: matching-validsig-overrides-verification-failure. **Confidence: High.** The image trust predicate requires a matching VALIDSIG line without requiring a successful verification exit or rejecting revoked-key status. GnuPG documents that VALIDSIG can accompany REVKEYSIG or expiry statuses: it proves cryptographic validity, not the accepted key state. The specified predicate can therefore accept a failed/unusable publisher signature before erasing the drive (PR-8; finding 4). | `docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:514-515; :538; :545` | Require successful GPG verification and an explicit acceptable status policy in addition to exact VALIDSIG fingerprint fields. Reject revoked-key status, define expiry handling, and test matching VALIDSIG plus revocation/nonzero exit before any Clear-Disk call. | open |
| F-008 | High | yes | control-defeat | mechanism: stale-success-record-survives-setup-failure. **Confidence: High.** Not writing a new record does not prevent import from seeing a failed setup. prepare preserves the members folder, and import reads every existing record. A rerun that fails CLI verification can leave its old record on the drive; unchanged SSH admin/password checks can still pass import, contradicting WP-U6's claimed failure barrier (PR-8; finding 4). | `docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:529-531; :546; docs/execution/plans/2026-11-07-usb-kit-hardening/task.md:57-59; .agent/fleet/usb/fleet_usb.py:73-74; :176-177; :211-215` | Invalidate or quarantine that member's previous success record before a setup attempt, or bind import to an explicit current setup result. Test a pre-existing success record followed by signature failure and prove it cannot import as a successful current setup. | open |
| F-009 | High | yes | behavior | **Confidence: High.** The mandated Git Bash locator fails on this Windows machine: git resolves under ucrt64/bin, so parents[1]/bin/bash.exe does not exist, while Bash exists under the actual Git installation root. The explicit fail-on-missing rule makes the row-3 harness fail despite Bash being installed and blocks the later Unix tests (PR-4; finding 7). | `docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:172-174; :283; :897-901; docs/execution/plans/2026-11-07-usb-kit-hardening/task.md:46` | Locate the Git installation root across supported cmd, mingw64 and ucrt64 layouts; validate candidate bin/bash.exe paths and explicitly avoid WSL. Test the observed ucrt64 layout before using the harness. | open |
| F-010 | High | yes | control-defeat | mechanism: privacy-scan-excludes-written-artifacts. **Confidence: High.** The privacy checks do not cover all files this public plan writes. AC-7 scans only the kit and omits personal/machine names; sanitize excludes scripts, execution plans and maintainer handoffs, and its raw-string rules target a generic source-project fixture. Plain refcheck checks references rather than identity literals. A newly introduced identifying literal in a plan, test, fleet.py or closeout artifact can pass these gates (PR-8; the user's public-package constraint). | `docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:276; :600-602; :629; scripts/sanitize.py:82; :105-119; :548-561; scripts/placeholders.py:59-70; docs/execution/plans/2026-11-04-fleet-agents/check_package_gates.py:25-28` | Add a privacy check over this plan's complete new/changed-file inventory, including tests, plans and closeout artifacts. Cover identifier classes and known local identity values without publishing those values; prove detection with synthetic mutations in each excluded file class. | open |
| F-011 | High | yes | control-defeat | mechanism: content-blind-tested-state. **Confidence: High.** H1-6b hashes HEAD, porcelain status and Python version, excluding file contents. An accidental edit from password-off to password-on in an already modified script leaves all three inputs unchanged, so stale passing full evidence still matches expected-state. This is a concrete false-pass unrelated to author forgery (PR-8, DR-7). | `docs/execution/plans/2026-11-07-usb-kit-hardening/task.md:69; docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:1012-1014; core/tools/durable_evidence.py:131-136` | Bind tested_state to actual tracked modifications and relevant untracked file bytes, with an explicit stable inventory, and compare that identity at the full run and review. Test a content change that preserves the same porcelain entry. | open |
| F-012 | High | yes | control-defeat | mechanism: validation-checks-a-different-registry. **Confidence: High.** H2-3b adds the known issue to the maintainer registry using explicit paths, then runs render --check without them. The tool defaults point to core/.agent/context, a different existing seed registry. The check can pass while the required maintainer Markdown remains stale; an unqualified render also targets the wrong tree (PR-4, PR-8; A-9 deliverable). | `docs/execution/plans/2026-11-07-usb-kit-hardening/task.md:79; core/tools/issue_triage/model.py:23-26; core/tools/issue_triage.py:368-377` | Pass --yaml .agent/context/known-issues.yaml --md .agent/context/known-issues.md before render for both generation and --check. Verify the rendered maintainer artifact contains the new issue. | open |
| F-013 | High | yes | behavior | **Confidence: High.** The human-required D-1 and D-2 decisions are silently resolved to A when unanswered. Rows 4 and 8a have only implementation dependencies, and the sequencing rule instructs them to run under A; recording the human's rulings is deferred to the later handoff. This does not preserve the user's requirement that both decisions wait for the human (PR-1, PR-4; explicit review scope). | `docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:101-102; :934-942; :960-962; docs/execution/plans/2026-11-07-usb-kit-hardening/task.md:35; :47; :53; :67; :102` | Keep A as the recommendation and block the dependent row until the human rules or expressly adopts the defaults. Record that resolution before writing code for the dependent package; do not infer it merely from an unanswered brief. | open |

### Counterexamples and attempted refutations

**F-001.** Refutation: the package-name grammar does reject option, local-file and URL operands, and normal sudo env_reset removes APT_CONFIG. Those facts rule out a default-policy argv exploit. They do not establish the advertised boundary on a member whose existing policy preserves the variable: the plan neither refuses that environment nor clears it. This is a conditional design counterexample, not a claim about any live member. APT reads APT_CONFIG before its normal configuration and supports root pre-invoke hooks. Sources: [APT configuration](https://manpages.debian.org/bookworm/apt/apt.conf.5.en.html), [sudo environment policy](https://raw.githubusercontent.com/sudo-project/sudo/main/docs/sudoers.man.in). No sudo or package manager was run.

**F-002.** Refutation: the key precedes password-off, the console guard preserves an on-screen recovery route, and sshd -T includes the checks performed by -t. Therefore a separate Windows -t invocation is not itself missing. But a syntactically valid configuration with PubkeyAuthentication no is not rejected by the plan's two-field predicate (the boundary explicitly ignores other fields). Writing authorized_keys cannot make disabled public-key authentication work. The import/probe happens after the access-changing transition. Source: [sshd testing semantics](https://man.openbsd.org/sshd.8).

**F-003.** Refutation: removing the newly introduced drop-in is correct on a first attempt with no prior file. WP-U5 and AC-16 do not distinguish that case from a rerun. A previous successful kit run is explicitly supported; its old bytes must survive a candidate refusal, just as WP-U5w already requires on Windows. The failure case can be an accidental malformed candidate or a transient failed check. This finding does not demand restoring an invalid candidate.

**F-004.** Refutation: the rich-rule addition is explicitly permanent. The subsequent service-removal operation is a separate invocation and has no stated permanent flag; permanence does not carry between commands. The firewalld manual states that runtime-only changes disappear on reload. This is the consequence of executing the listed arguments, rather than a claim about already implemented code. Source: [firewall-cmd runtime and permanent semantics](https://firewalld.org/documentation/man-pages/firewall-cmd.html).

**F-005.** Refutation: installing firewalld does not define a running-daemon prerequisite, and the plan explicitly promises a first-start path. The listener check before a first start does not make earlier daemon calls succeed. firewall-offline-cmd is absent from both the recipe and the named stub inventory. Source: [the offline client](https://firewalld.org/documentation/man-pages/firewall-offline-cmd.html).

**F-006.** Refutation: Domain, Private with LocalSubnet is the correct scope for the rule being created/updated, and a Public connection correctly stops this setup. A second independently named allow rule remains effective, including when the machine later changes profile. A-4 deliberately preserves such rules, so the missing deliverable is enumeration/reporting, not their deletion. Sources: [rule scope](https://learn.microsoft.com/en-us/powershell/module/netsecurity/new-netfirewallrule), the current named-rule-only code, and the absence of a Windows broader-rule case from AC-13/AC-23.

**F-007.** Refutation: the described exact-name hash match, detached signature filename, fresh GNUPGHOME, full fingerprint comparison, and optional primary-key fingerprint handle the specifically listed bad-line, missing-signature, unknown-key and wrong-file cases. No incorrect VALIDSIG field index is specified. The surviving defect is acceptance of a matching VALIDSIG without a successful/acceptable verification outcome; the primary GnuPG status contract explicitly permits this record alongside revocation and expiry statuses. Source: [GnuPG DETAILS, VALIDSIG](https://github.com/gpg/gnupg/blob/master/doc/DETAILS).

**F-008.** Refutation: no fresh record is written on verification failure, and execution's human rows should stop if setup reports failure. That does not establish the stronger shipped-kit claim that import can never see that member. The committed prepare makes members with exist_ok=True; it does not empty it. import then globs all records without a current-attempt result. A previously successful member can therefore remain importable after a failed rerun. Preserve other members' records when repairing this.

**F-009.** Observed directly: the current Git executable is under its installation's ucrt64/bin directory. The exact Named-definition formula returns a nonexistent candidate; bin/bash.exe under the actual installation root exists. This is an executable-discovery algorithm failure across Git layouts, not a missing installed dependency. WSL was neither selected nor run. The same installation-root resolver should be used for the Git GPG fallback if that code reuses this formula.

**F-010.** Refutation: AC-7 does cover several literal classes inside the kit, the source-project substitution gate checks all of its defined source strings, and the existing SetupMember Pester suite checks its own distinct script. None extends coverage to all new/changed files here. Refcheck's plain invocation has no identity-token arguments; it validates references. The omission follows from the scanners' actual inventories and rule definitions, not from a hypothetical forged receipt. No actual identifying values are reproduced in this review.

**F-011.** Refutation: the input hash is recomputed independently and the final full run is fresh at the moment it runs. The defect is the inputs to the hash: changing bytes in an already modified tracked file leaves HEAD and porcelain unchanged; Python version also remains unchanged. The durable-evidence reader compares tested_state to this same identifier. The peer task has the same form, which confirms the precedent but does not detect this accidental-edit case. No repository mutation was performed to demonstrate the deterministic collision.

**F-012.** Refutation: the add command correctly supplies both maintainer paths, and both root and core issue stores exist. The subsequent check drops those global options; model.py derives defaults from core/tools/issue_triage/model.py, hence core/.agent/context. A healthy seed render can pass without examining the newly modified maintainer pair. The correction is the explicit target pair on both render commands, not a new tool or schema.

**F-013.** Refutation: overall execution is human-gated and every commit still requires the human; this review does not dispute either protection. The remaining ambiguity is narrower: the user explicitly leaves both value decisions pending, while these rows prescribe A for an unanswered brief. A human may expressly adopt the recommended defaults at the same execution gate; the plan must record that resolution before the dependent work, rather than treating silence as it.

### Nonblocking correction notes

- **Low — PC's no-commit branch:** `task.md:41` permits `[x] n/a`, but its unconditional `git ls-files --error-unmatch` fails when the plan remains untracked. Give the n/a branch an appropriate validation. This does not authorize a commit.
- **Low — exclusion label:** `implementation-plan.md:666` calls the separate setup-member installer issue `deferred` without a MEU target. The user's kit scope and A-9 substantively justify leaving that file unchanged; label this an evidenced out-of-scope item with its issue follow-up.
- **Low — console-walk bound repeated:** `implementation-plan.md:201-202,429`. Keep the Named definition canonical and refer to it from the AC.
- **Low — firewall profile set repeated:** `implementation-plan.md:360-375,787,907` and `task.md:48`. Keep WP-U4's profile policy canonical and reference it elsewhere.
- **Low — password policy repeated:** `implementation-plan.md:156-160,409-411,431,454-458,472,917`. Retain named policy/OS sequence definitions and references rather than parallel restatements.
- **Low — helper permissions repeated:** `implementation-plan.md:152-155,317-318,337`. Keep ownership/modes canonical in the Named definitions and reference them in the AC.

The named existing-test exception is the only sourced existing-test edit needed: `scripts/tests/test_fleet_agent.py:1912-1913`. The parametrized run suite automatically loses the retired-command cases without being edited. No commit-trailer absence is a finding.

## Checklist Results

### Information Retrieval

| Check | Result | Command / procedure | Exit | Evidence |
|-------|--------|---------------------|------|----------|
| AC source labels and full scope read | pass | Manual line-by-line source comparison by Codex | null | All 25 unique ACs have allowed source labels; coverage matrix below |
| Task shape | pass | `rtk proxy python -X utf8 core/tools/lint_task_contract.py --task docs/execution/plans/2026-11-07-usb-kit-hardening/task.md` | 0 | 41 rows; 10 columns; 39 command contracts checked; 2 view_file exemptions; dependencies resolve and are acyclic |
| Referenced artifacts | pass | Python Path existence sweep of task executables, schemas and templates | 0 | Existing references exist; three plan-local checkers and three new test files are explicitly scheduled |
| Not-started status | pass | `rtk git status --short` plus file existence reads | 0 | Four pre-existing modified kit files; untracked plan folder; no correlated implementation handoff or new USB test file |

### Plan Review

| Check | Result | Command / procedure | Exit | Evidence |
|-------|--------|---------------------|------|----------|
| PR-1 | partial | Manual coverage review; R1-COVERAGE below | null | All work packages and AC-1 through AC-25 map to task rows; F-013 leaves the stated human-decision prerequisite inconsistent with executable sequencing. |
| PR-2 | pass | Manual coverage review; R1-COVERAGE below | null | No correlated implementation handoff or new USB tests/checkers exist. All 41 task rows remain unchecked. Four dirty kit files are the separately owned work identified by the user. |
| PR-3 | pass | Manual coverage review; R1-COVERAGE below | null | Task linter exited 0: 41 rows, 10 columns, 39 checked command contracts, 2 view_file exemptions; dependencies resolve and are acyclic. |
| PR-4 | fail | Manual coverage review; R1-COVERAGE below | null | F-001 through F-009 and F-012 expose concrete security, command-discovery or ordering failures. Windows PowerShell 5.1 parsed all 38 extracted command cells without errors. |
| PR-5 | pass | Manual coverage review; R1-COVERAGE below | null | All AC rows carry Human-approved, Local Canon or Research-backed sources. Referenced existing executable paths exist; absent new artifacts are scheduled by row 1 or their coder rows. |
| PR-6 | pass | Manual coverage review; R1-COVERAGE below | null | Canonical project, plan-review and execution-review paths are explicit. Round 1 of 3; a resubmission census is not yet applicable. Findings are actionable through /plan-corrections. |
| PR-7 | partial | Manual coverage review; R1-COVERAGE below | null | Scope is the seven user findings; setup-member.ps1 is outside the named kit scope and receives an issue. Its deferred label lacks a MEU target but the exclusion itself is substantively sourced; correction is nonblocking. |
| PR-8 | fail | Manual coverage review; R1-COVERAGE below | null | F-006 through F-012 name production entrypoints and concrete accepting states with missing protection; F-001 identifies a conditional environment-controlled root path. None depends on forged author evidence. |
| PR-9 | partial | Manual coverage review; R1-COVERAGE below | null | Repeated policy literals occur in the profile set, console-walk bound, password-off policy and helper permissions. Canonical-definition references would reduce correction drift; these are nonblocking notes. |

### Design Review

| Check | Result | Command / procedure | Exit | Evidence |
|-------|--------|---------------------|------|----------|
| DR-1 | n/a | n/a | null | This is an unstarted plan, not a completed implementation handoff. |
| DR-2 | pass | Manual source/command review; R1-COVERAGE below | null | The retired-word sweep found only two fleet.py constants and the single named existing-test exception. Both constants and that expectation are scheduled; no additional existing-test edit is needed. |
| DR-3 | pass | Manual source/command review; R1-COVERAGE below | null | The manifest relocation, update smoke step, bootstrap inbound-port correction and both README changes are explicitly inventoried. |
| DR-4 | fail | Manual source/command review; R1-COVERAGE below | null | The planned negative cases omit preserved package-manager environment, password-only SSH config, a previous drop-in, stopped-daemon firewalld behavior, revoked-key status and a stale member record. |
| DR-5 | pass | Manual source/command review; R1-COVERAGE below | null | Commands, exits and observations are recorded below. Targeted existing pytest and peer Pester passed; the broader pytest run was stopped without a complete result and is not represented as passing. |
| DR-6 | partial | Manual source/command review; R1-COVERAGE below | null | F-006 conflicts with the global broader-rule reporting promise; F-008 contradicts the record-based signature barrier; F-012 targets a different issue registry. |
| DR-7 | fail | Manual source/command review; R1-COVERAGE below | null | F-011 demonstrates that the proposed state identity cannot distinguish a relevant content edit from the tested state. |
| DR-8 | fail | Manual source/command review; R1-COVERAGE below | null | D-1's package-only residual needs the environment qualification in F-001; lockout and record-barrier claims are stronger than the specified mechanisms. D-2's installer-before-verification limitation is explicitly and correctly disclosed. |

### Executed observations

The pytest/Pester child commands below ran through a Python launcher invoked with `rtk proxy`. The launcher disabled bytecode writes and set TEMP/TMP and pytest basetemp inside the permitted review scratch folder. Receipt names below are locators; decisive results are preserved here.

| Check | Command / procedure | Exit | Observation |
|-------|---------------------|------|-------------|
| Existing named-test exception plus bootstrap | `python -X utf8 -m pytest scripts/tests/test_fleet_agent.py::test_ac32_forbidden_commands_are_unchanged scripts/tests/test_fleet_bootstrap.py -q -p no:cacheprovider --basetemp <review scratch>/pytest-targeted` | 0 | **42 passed in 45.13s** |
| Existing Pester and peer runner | `pwsh -NoProfile -File docs/execution/plans/2026-11-04-fleet-agents/run_pester.ps1 scripts/tests/SetupMember.Tests.ps1` | 0 | **65 passed, 0 failed, 0 skipped**; gate Result=Passed, FailedBlocks=0, FailedContainers=0, Uncovered=0; runner self-check passed |
| Windows PowerShell 5.1 parsing | `rtk proxy powershell -NoProfile -File <review scratch>/parse-cells.ps1` | 0 | All **38** extracted command cells parsed with **0** errors; both current kit .ps1 files parsed with **0** errors |
| Git Bash discovery | Python shutil.which/Path inspection of the exact named formula and actual installation root | 0 | Formula candidate absent; actual installation-root bin/bash.exe present |
| Identity counterexample | Pure calculation with changed script contents and unchanged HEAD/porcelain/version inputs | 0 | Content change not detected by the specified identifier |
| Wider existing fleet pytest attempt | `python -X utf8 -m pytest scripts/tests/test_fleet_agent.py scripts/tests/test_fleet_bootstrap.py -q -p no:cacheprovider --basetemp <review scratch>/pytest` | 15 (stopped) | Stopped after roughly twelve minutes; partial output reached beyond 44% and included one failure, but no traceback or completed summary. **Incomplete; not a passing baseline and not used to diagnose a plan finding.** Its owned process tree was stopped. |
| No-op prerequisites | File existence reads | 0 | BUILD_PLAN hub, package API and maintainer MEU registry absent, matching rows 15, H1-3 and H1-4; run-parameters policy absent; configured caps match 3 plan / 6 execution rounds |

Receipts: `receipt: C:/Temp/zorivest/usb-kit-plan/review-r1/targeted-existing-tests.txt`, `receipt: C:/Temp/zorivest/usb-kit-plan/review-r1/existing-pester.txt`, `receipt: C:/Temp/zorivest/usb-kit-plan/review-r1/fleet-tests.txt`, and `scratch: C:/Temp/zorivest/usb-kit-plan/review-r1/parse-cells.ps1`.

```json
{
  "schema_version": "evidence.v1",
  "id": "R1-COVERAGE",
  "phase": "manual",
  "procedure": "Read both target files in full with numbered lines; inspect committed/current kit source and separate dirty diffs; compare the named canonical docs, peer checker and Pester runner; trace every task, AC, Named definition, decision and stop condition; cross-check each surviving counterexample against those sources and the cited primary public documentation.",
  "observer": "Codex",
  "command": null,
  "exit_code": null,
  "result": "fail",
  "observed": "Thirteen delivery-level findings survive refutation. Existing targeted pytest and Pester checks passed; the wider pytest attempt was stopped incomplete. No live-member claim is made."
}
```

## Coverage census

### Work packages and acceptance criteria

| Package | AC coverage and disposition |
|---------|-----------------------------|
| WP-U1 | AC-1/2: both constants, exact existing-test exception and scan boundaries verified. AC-3: human row 2a, hub-first update and old-hello refusal are coherent. Only the two constants and named old-test expectation currently contain the retired word in the requested scan roots. |
| WP-U2 | AC-4: load guards, -LibraryOnly and mandatory-Iso parameter-set design are coherent. AC-5: bash 3.2 exclusions and LF requirements cover the new helper when created; F-009 blocks the stated Windows discovery path. AC-6/7/12: green-first guards are explicitly sourced exceptions (A-13); F-010 concerns the wider public-output boundary. |
| WP-U3 | AC-8: today's ALL grant gives a real initial failure. AC-9: exact sudoers command path, root-only runas, user grammar, checked temp file and owner/modes are coherent. AC-10: arity/package-name checks exclude the listed argv attacks; F-001 adds the surviving environment route. AC-11: all declared outcomes are exhaustively mapped and unknown output fails closed. F-013 applies before implementation. |
| WP-U4 | AC-13: Domain/Private plus LocalSubnet is valid; Public preflight precedes changes and never changes the category. F-006 is the missing second-rule warning. |
| WP-U5 | AC-14 Unix: parent-prefix design covers sshd-session; fail-open loop/missing-parent behavior and tmux limit are disclosed. No concrete OS implementation exists yet to certify its ps field selection. AC-15: subnet/key replacement, preserved other keys and UFW listener stop are specified; F-004/005 affect firewalld. AC-16: syntax/value checks precede reload, but F-002/003 remain. |
| WP-U5w | AC-14 Windows: CIM parent fields and sshd/WinRM names are coherent, and the stated fail-open cases are explicit. AC-17: marked block order and old-byte restore are coherent; -T includes -t testing, refuting a separate missing-Windows--t finding. F-002 remains. |
| WP-U5b | AC-18: named import entrypoint, disabled client authentication methods, exact allowed method list, failure counting and --no-test exception are explicit. The probe is after the admin check and cannot rescue F-002. A Match rule for another account is not proven absent by probing the member account; retain that limit honestly in the resulting docs. |
| WP-U6 | AC-19: fingerprint/primary-key field semantics and exact single filename/hash matching are coherent; missing signature, unknown key, bad/suffix/duplicate hash-line and wrong-image cases fail as described. F-007 concerns the unhandled verification outcome. AC-20: conditional CLI branch, stop condition 4 and no-pipe guard are explicit; D-2 correctly admits installer execution before checking the binary. F-008 and F-013 remain. |
| WP-U7 | AC-21: both malformed manifest lines, fleet-section move, refresh smoke step, bootstrap test invariants and both READMEs/Undo paths are inventoried. Helper verbs replace the cited raw sudo instructions; no extra existing-test change is planned. Restore instructions must follow F-003's corrected rerun behavior. |
| WP-U8 | AC-22: peer comparison and own-file AC inventory are explicit; F-010 affects privacy, not the validity of baseline comparison itself. AC-23: canonical Windows rule/probe covered; F-006 and F-008 remain. AC-24: helper-only admin/firewall/password checks covered, with F-004/005. AC-25: macOS lacks a firewall by explicit scope; from= and helper checks are planned; missing hardware is a legitimate row-14 blocker. No live check was performed. |

### Named definitions

| Definition | Disposition |
|------------|-------------|
| Kit; Drive folder | Correct current directories and prepare/import folder contract. |
| Helper; Sudoers file | Fixed path/argv and ownership design reviewed; visudo -cf is check-only syntax for the scratch candidate. It is not a command that starts an editor. F-001 qualifies the runtime environment boundary. No real sudoers file was opened or visudo invoked. |
| Drop-in; Marked block | First-value placement is coherent; F-002 affects key usability and F-003 affects Unix rollback. Windows retains the old bytes. |
| Member subnets | IPv4 scope, loopback/link-local exclusions, Linux CIDR and macOS hex masks are specified; pure bash avoids an undeclared Python dependency. IPv6 is expressly excluded. |
| Load guard | Bash source/run distinction is coherent; explicit-path functions and PS library switches permit a safe test seam after row 3. |
| Git bash | F-009; the actual installed dependency is available. |
| Stub folder | All named daemon/system tools considered; inactive firewalld behavior and environment assertions must be added for F-001/005. Tests must not replace the entire PATH with stubs and thereby lose ordinary shell utilities. |
| Admin check; Outcomes | Exact two-line Unix output and Windows IsInRole path are bound to import; unknown output fails closed. No direct shell argument-smuggling route survives the stated fixed-argv grammar. This does not certify unimplemented helper code. |
| Probe | RFC method-list check has a production import call chain and negative cases; timeout/missing list fails. |
| Console guard | Both platforms' parent-walk contracts and disclosed fail-open bounds reviewed; no claim of live macOS validation. |

### Task rows

| Rows | Disposition |
|------|-------------|
| PC | Human-only commit direction preserved; nonblocking n/a validation note above. |
| 0 | Four dirty kit files remain human-owned. The clean-tree/kept-step receipt is explicit; no agent staging, stash, restore or commit is authorized. |
| 1 | All three absent checker/runner artifacts are scheduled before use, with real peer sources; baseline and selftests precede code. A red baseline correctly stops for the human. The stopped broad review run cannot substitute for this execution baseline. |
| 2, 2a | Both constants and the named expected set covered; row 2a is explicitly human-gated and independently blocks H1 closeout. Row 3 deliberately depends on 2 rather than requiring the live update first. |
| 3 | Guard/characterization exceptions are explicit; F-009 prevents the stipulated Bash tests on this machine. Tests can fail as assertions after loading inside test scopes; no absent top-level Python import is mandated. |
| 4 | AC-8 through AC-11 and copied helper covered; F-001 and F-013 remain. |
| 5 | F-006; correct canonical profile/address settings do not replace reporting other rules. |
| 6 | F-002 through F-005. Determine the Linux SSH unit even when it was already listening; today's source sets its service variable inside the start-only branch. The new reload path must not reuse an unset service variable. |
| 6a | Windows rollback and Pester forms reviewed; F-002 remains. |
| 7 | Probe sequencing, failure count and --no-test skip are explicit. |
| 8 | Real image verification functions precede disk erase; F-007 remains. Probe-2 is an execution-time network action, not performed during this review. |
| 8a | Kept/discarded CLI branches and conditional red/guard mode align with row 0. Probe-1 reads current vendor docs before coding; absence of a usable check must stop for the human, not silently select option B. F-008/F-013 remain. |
| 9 | All five documentation outputs and test invariants match WP-U7. |
| 10, 11 | Fleet/targeted/Pester regression commands and gate inventory match the plan. F-010 affects privacy coverage. |
| 12, 13, 14 | Explicitly human-gated prepare/setup/import/check sequence. import checks all drive records, so all recorded members must be on. F-008 concerns retained records. Row 14 can be [B] without macOS hardware, with a linked follow-up; no substitute live success is claimed. |
| 15 | BUILD_PLAN absence verified. |
| H1-1, H1-2 | Human-row dependencies are named, including row 14; checks do not authorize crossing an unresolved dependency. Full suite includes the targeted/regression files; relevant code changes require the specified live reruns. A blocked live row must not be called a passed runtime AC. |
| H1-3, H1-4, H1-5 | No-op prerequisites and source-read targets exist or are absent as stated. |
| H1-6, H1-6a | Handoff and coverage checks have real tools; human rulings and red/guard/live receipts must be recorded honestly. |
| H1-6b | F-011; independent recomputation does not fix incomplete identity inputs. |
| H1-7, H1-7a, H1-7b | Independent execution-review dispatch, six-round cap, target-bound state parsing and matching approved ledger requirements are coherent. No dispatch was launched by this review. |
| H2-1, H2-2, H2-3 | Reflection/template/schema and metric destinations exist; after-review sequencing is explicit. |
| H2-3a | No grouping source is an evidenced no-op for this direct user request. |
| H2-3b | F-012. |
| H2-3c, H2-4 | Main-tree/manual scope and task-contract closeout are coherent; no credits execution is authorized. |
| H2-5, COMMIT, H2-6 | Draft only without the human's commit direction; author-address check remains mandatory. No push is authorized. Final completion depends on the preceding gates, not merely on editing the status text. |

### Peer-plan comparison

The copied Pester runner checks the full run Result, passed test count, failed tests/blocks/containers, and requested-path discovery. Its probes cover discovery, BeforeAll and AfterAll failures; the existing run reproduced a pass. Loading kit scripts in Describe/BeforeAll with AC-prefixed names is consistent with useful red receipts; the Python red checker must still be implemented and selftested at row 1.

The peer package checker compares normalized failure lines and inventories tests in its own named files; the adaptation changes its AC count, live exclusions, manifest entries, filenames and baseline name as required. This comparison does not add a privacy scanner and does not repair the peer task's identical status-only freshness hash. Precedent was used as source, not as an exemption from the user's current requirements.

## Verdict

`changes_required` — resolve F-001 through F-013 through `/plan-corrections`, retaining the findings' counterexamples and adding their negative assertions. This is round 1; the cap is 3. A resubmission must include the protocol's untruncated blast-radius census and per-hit dispositions.

D-1 and D-2 remain pending for the human. D-1's fixed-argv/package grammar is materially better bounded than today's ALL grant, but its claimed residual needs the environment correction. D-2 honestly admits that installer code runs before binary verification; the review does not demand eliminating a risk the brief explicitly offers to the human. Windows full administrator access, repository package install scripts, the macOS firewall exclusion and missing macOS live hardware remain declared limits, not new blockers invented by this review.

Execution remains manual (`policy_missing`); every commit needs the human's word and nothing is pushed. The separately owned four dirty kit files remain untouched. No implementation or corrections were started.

Review-artifact validation passed against `core/.agent/schemas/review-verdict.schema.json`; the frontmatter begins with `---`, mode is `plan`, and the structured target is the plan folder. A final literal check found zero email, fixed-user-path or IPv4 literals in this verdict. The repeated-literal sweep is preserved untruncated at `receipt: C:/Temp/zorivest/usb-kit-plan/review-r1/repeated-literal-census.txt` (13 matching lines for the queried clusters).

🕐 Completed: 2026-11-07 11:43 (EST)

## Structured verdict

```json
{
  "schema_version": "review-verdict.v1",
  "date": "2026-11-07",
  "review_mode": "plan",
  "target_plan": "docs/execution/plans/2026-11-07-usb-kit-hardening",
  "agent": "Codex",
  "requested_verbosity": "detailed",
  "verdict": "changes_required",
  "summary": "Round 1: changes required. Thirteen delivery-level findings cover privilege/environment isolation, SSH safety, firewall behavior, signature handling, stale records, the Windows Bash locator, privacy coverage, evidence freshness, the issue-registry path and unresolved human decisions. Existing targeted tests passed (42 pytest, 65 Pester); the broader pytest run was stopped incomplete. Nonblocking notes concern PC's no-commit branch, the deferral label and repeated policy literals. D-1 and D-2 remain for the human.",
  "findings": [
    {
      "id": "F-001",
      "severity": "High",
      "confidence": "Medium",
      "finding": "D-1 A constrains argv and PATH but leaves the package-manager environment unconstrained. On a member whose existing sudo policy preserves APT_CONFIG, an attacker with the hub key can select an agent-writable APT configuration containing a root pre-invoke hook, then invoke the allowed helper with an ordinary package name. This is a root-command route outside the stated repository-package residual risk (PR-4, PR-8).",
      "file_line": "docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:308; :314-318; :127-129; :940-946",
      "recommendation": "Specify and test a clean allowlisted environment for privileged child commands, pin a trusted system PATH, and address interpreter startup environment before claiming the package-only residual. Include a poisoned APT_CONFIG negative case; document any required sudo-policy precondition.",
      "status": "open"
    },
    {
      "id": "F-002",
      "severity": "High",
      "confidence": "High",
      "finding": "The password-off checks prove syntax and two password settings, without establishing that the installed hub key can authenticate. An existing valid PubkeyAuthentication no configuration passes the stated checks; both Unix and Windows then disable password authentication and leave the hub unable to sign in. The later import only discovers the lockout (PR-4, PR-8; Goal finding 3 and A-12).",
      "file_line": "docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:394-411; :422; :454-458; :472; :877-881",
      "recommendation": "Make working key authentication a prerequisite for password-off, with a reversible confirmation step or equivalent effective-config checks and rollback until the hub key is confirmed. Test a valid password-only SSH configuration on both paths.",
      "status": "open"
    },
    {
      "id": "F-003",
      "severity": "High",
      "confidence": "High",
      "finding": "A failed Unix rerun removes the drop-in even when a previous successful run installed it. With a pre-existing valid password-off drop-in, a failed candidate/check destroys the previous protection; macOS applies the missing drop-in on the next connection, and Linux loses it on a later reload or reboot. AC-16 explicitly requires this destructive failure behavior (PR-4, DR-4; finding 3).",
      "file_line": "docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:409-411; :431; :917-921",
      "recommendation": "Snapshot the old drop-in bytes, ownership and mode; restore them on failure, removing the candidate only when no previous file existed. Test both first-run and rerun failures, and validate restored configuration before any reload.",
      "status": "open"
    },
    {
      "id": "F-004",
      "severity": "High",
      "confidence": "High",
      "finding": "The firewalld recipe makes the rich rules permanent but specifies --remove-service=ssh followed by --reload without making the removal permanent. Following those argv literally removes only the runtime service; reload reinstates the permanent unrestricted SSH service, defeating the subnet limit (PR-4, DR-4; finding 3).",
      "file_line": "docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:404-406; :430; docs/execution/plans/2026-11-07-usb-kit-hardening/task.md:49",
      "recommendation": "Specify zone-scoped permanent removal explicitly, reconcile this standard-service change with A-4, and assert both runtime and permanent state after reload and a repeat run.",
      "status": "open"
    },
    {
      "id": "F-005",
      "severity": "High",
      "confidence": "High",
      "finding": "The first-start firewalld path tries to enumerate active zones and configure permanent rules before starting the daemon, using firewall-cmd. That client requires a running daemon. A member with firewalld installed but stopped cannot reach the promised safe first enable; no offline configuration branch/tool is planned (PR-4; WP-U5 and A-11).",
      "file_line": "docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:397-406; :175-177; :430; :867-871",
      "recommendation": "Define a stopped-daemon branch using offline configuration with explicit target zones, validate it, then perform the listener guard and start. Add stubs that return NOT_RUNNING for daemon-client calls until start, rather than canned success.",
      "status": "open"
    },
    {
      "id": "F-006",
      "severity": "High",
      "confidence": "High",
      "finding": "WP-U4 only manages OpenSSH-Server-In-TCP. No Windows task or assertion enumerates and reports a differently named broader inbound SSH rule. With a second enabled broad rule, the canonical rule and AC-23 can look correct while SSH remains reachable through the broader rule without the A-4 warning (PR-8; finding 2 and A-4).",
      "file_line": "docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:117; :358-375; :630; docs/execution/plans/2026-11-07-usb-kit-hardening/task.md:48; .agent/fleet/usb/setup-windows.ps1:72-83",
      "recommendation": "Add Windows effective-rule enumeration and reporting for other enabled inbound allows covering SSH, including broad profile/address/port matches. Preserve those rules as A-4 requires and test a canonical rule beside a broader second rule.",
      "status": "open"
    },
    {
      "id": "F-007",
      "severity": "High",
      "confidence": "High",
      "finding": "The image trust predicate requires a matching VALIDSIG line without requiring a successful verification exit or rejecting revoked-key status. GnuPG documents that VALIDSIG can accompany REVKEYSIG or expiry statuses: it proves cryptographic validity, not the accepted key state. The specified predicate can therefore accept a failed/unusable publisher signature before erasing the drive (PR-8; finding 4).",
      "file_line": "docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:514-515; :538; :545",
      "recommendation": "Require successful GPG verification and an explicit acceptable status policy in addition to exact VALIDSIG fingerprint fields. Reject revoked-key status, define expiry handling, and test matching VALIDSIG plus revocation/nonzero exit before any Clear-Disk call.",
      "status": "open"
    },
    {
      "id": "F-008",
      "severity": "High",
      "confidence": "High",
      "finding": "Not writing a new record does not prevent import from seeing a failed setup. prepare preserves the members folder, and import reads every existing record. A rerun that fails CLI verification can leave its old record on the drive; unchanged SSH admin/password checks can still pass import, contradicting WP-U6's claimed failure barrier (PR-8; finding 4).",
      "file_line": "docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:529-531; :546; docs/execution/plans/2026-11-07-usb-kit-hardening/task.md:57-59; .agent/fleet/usb/fleet_usb.py:73-74; :176-177; :211-215",
      "recommendation": "Invalidate or quarantine that member's previous success record before a setup attempt, or bind import to an explicit current setup result. Test a pre-existing success record followed by signature failure and prove it cannot import as a successful current setup.",
      "status": "open"
    },
    {
      "id": "F-009",
      "severity": "High",
      "confidence": "High",
      "finding": "The mandated Git Bash locator fails on this Windows machine: git resolves under ucrt64/bin, so parents[1]/bin/bash.exe does not exist, while Bash exists under the actual Git installation root. The explicit fail-on-missing rule makes the row-3 harness fail despite Bash being installed and blocks the later Unix tests (PR-4; finding 7).",
      "file_line": "docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:172-174; :283; :897-901; docs/execution/plans/2026-11-07-usb-kit-hardening/task.md:46",
      "recommendation": "Locate the Git installation root across supported cmd, mingw64 and ucrt64 layouts; validate candidate bin/bash.exe paths and explicitly avoid WSL. Test the observed ucrt64 layout before using the harness.",
      "status": "open"
    },
    {
      "id": "F-010",
      "severity": "High",
      "confidence": "High",
      "finding": "The privacy checks do not cover all files this public plan writes. AC-7 scans only the kit and omits personal/machine names; sanitize excludes scripts, execution plans and maintainer handoffs, and its raw-string rules target a generic source-project fixture. Plain refcheck checks references rather than identity literals. A newly introduced identifying literal in a plan, test, fleet.py or closeout artifact can pass these gates (PR-8; the user's public-package constraint).",
      "file_line": "docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:276; :600-602; :629; scripts/sanitize.py:82; :105-119; :548-561; scripts/placeholders.py:59-70; docs/execution/plans/2026-11-04-fleet-agents/check_package_gates.py:25-28",
      "recommendation": "Add a privacy check over this plan's complete new/changed-file inventory, including tests, plans and closeout artifacts. Cover identifier classes and known local identity values without publishing those values; prove detection with synthetic mutations in each excluded file class.",
      "status": "open"
    },
    {
      "id": "F-011",
      "severity": "High",
      "confidence": "High",
      "finding": "H1-6b hashes HEAD, porcelain status and Python version, excluding file contents. An accidental edit from password-off to password-on in an already modified script leaves all three inputs unchanged, so stale passing full evidence still matches expected-state. This is a concrete false-pass unrelated to author forgery (PR-8, DR-7).",
      "file_line": "docs/execution/plans/2026-11-07-usb-kit-hardening/task.md:69; docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:1012-1014; core/tools/durable_evidence.py:131-136",
      "recommendation": "Bind tested_state to actual tracked modifications and relevant untracked file bytes, with an explicit stable inventory, and compare that identity at the full run and review. Test a content change that preserves the same porcelain entry.",
      "status": "open"
    },
    {
      "id": "F-012",
      "severity": "High",
      "confidence": "High",
      "finding": "H2-3b adds the known issue to the maintainer registry using explicit paths, then runs render --check without them. The tool defaults point to core/.agent/context, a different existing seed registry. The check can pass while the required maintainer Markdown remains stale; an unqualified render also targets the wrong tree (PR-4, PR-8; A-9 deliverable).",
      "file_line": "docs/execution/plans/2026-11-07-usb-kit-hardening/task.md:79; core/tools/issue_triage/model.py:23-26; core/tools/issue_triage.py:368-377",
      "recommendation": "Pass --yaml .agent/context/known-issues.yaml --md .agent/context/known-issues.md before render for both generation and --check. Verify the rendered maintainer artifact contains the new issue.",
      "status": "open"
    },
    {
      "id": "F-013",
      "severity": "High",
      "confidence": "High",
      "finding": "The human-required D-1 and D-2 decisions are silently resolved to A when unanswered. Rows 4 and 8a have only implementation dependencies, and the sequencing rule instructs them to run under A; recording the human's rulings is deferred to the later handoff. This does not preserve the user's requirement that both decisions wait for the human (PR-1, PR-4; explicit review scope).",
      "file_line": "docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:101-102; :934-942; :960-962; docs/execution/plans/2026-11-07-usb-kit-hardening/task.md:35; :47; :53; :67; :102",
      "recommendation": "Keep A as the recommendation and block the dependent row until the human rules or expressly adopts the defaults. Record that resolution before writing code for the dependent package; do not infer it merely from an unanswered brief.",
      "status": "open"
    }
  ],
  "checklist_results": [
    {
      "check": "PR-1",
      "result": "partial",
      "evidence": "All work packages and AC-1 through AC-25 map to task rows; F-013 leaves the stated human-decision prerequisite inconsistent with executable sequencing."
    },
    {
      "check": "PR-2",
      "result": "pass",
      "evidence": "No correlated implementation handoff or new USB tests/checkers exist. All 41 task rows remain unchecked. Four dirty kit files are the separately owned work identified by the user."
    },
    {
      "check": "PR-3",
      "result": "pass",
      "evidence": "Task linter exited 0: 41 rows, 10 columns, 39 checked command contracts, 2 view_file exemptions; dependencies resolve and are acyclic."
    },
    {
      "check": "PR-4",
      "result": "fail",
      "evidence": "F-001 through F-009 and F-012 expose concrete security, command-discovery or ordering failures. Windows PowerShell 5.1 parsed all 38 extracted command cells without errors."
    },
    {
      "check": "PR-5",
      "result": "pass",
      "evidence": "All AC rows carry Human-approved, Local Canon or Research-backed sources. Referenced existing executable paths exist; absent new artifacts are scheduled by row 1 or their coder rows."
    },
    {
      "check": "PR-6",
      "result": "pass",
      "evidence": "Canonical project, plan-review and execution-review paths are explicit. Round 1 of 3; a resubmission census is not yet applicable. Findings are actionable through /plan-corrections."
    },
    {
      "check": "PR-7",
      "result": "partial",
      "evidence": "Scope is the seven user findings; setup-member.ps1 is outside the named kit scope and receives an issue. Its deferred label lacks a MEU target but the exclusion itself is substantively sourced; correction is nonblocking."
    },
    {
      "check": "PR-8",
      "result": "fail",
      "evidence": "F-006 through F-012 name production entrypoints and concrete accepting states with missing protection; F-001 identifies a conditional environment-controlled root path. None depends on forged author evidence."
    },
    {
      "check": "PR-9",
      "result": "partial",
      "evidence": "Repeated policy literals occur in the profile set, console-walk bound, password-off policy and helper permissions. Canonical-definition references would reduce correction drift; these are nonblocking notes."
    },
    {
      "check": "DR-1",
      "result": "n/a",
      "evidence": "This is an unstarted plan, not a completed implementation handoff."
    },
    {
      "check": "DR-2",
      "result": "pass",
      "evidence": "The retired-word sweep found only two fleet.py constants and the single named existing-test exception. Both constants and that expectation are scheduled; no additional existing-test edit is needed."
    },
    {
      "check": "DR-3",
      "result": "pass",
      "evidence": "The manifest relocation, update smoke step, bootstrap inbound-port correction and both README changes are explicitly inventoried."
    },
    {
      "check": "DR-4",
      "result": "fail",
      "evidence": "The planned negative cases omit preserved package-manager environment, password-only SSH config, a previous drop-in, stopped-daemon firewalld behavior, revoked-key status and a stale member record."
    },
    {
      "check": "DR-5",
      "result": "pass",
      "evidence": "Commands, exits and observations are recorded below. Targeted existing pytest and peer Pester passed; the broader pytest run was stopped without a complete result and is not represented as passing."
    },
    {
      "check": "DR-6",
      "result": "partial",
      "evidence": "F-006 conflicts with the global broader-rule reporting promise; F-008 contradicts the record-based signature barrier; F-012 targets a different issue registry."
    },
    {
      "check": "DR-7",
      "result": "fail",
      "evidence": "F-011 demonstrates that the proposed state identity cannot distinguish a relevant content edit from the tested state."
    },
    {
      "check": "DR-8",
      "result": "fail",
      "evidence": "D-1's package-only residual needs the environment qualification in F-001; lockout and record-barrier claims are stronger than the specified mechanisms. D-2's installer-before-verification limitation is explicitly and correctly disclosed."
    }
  ]
}
```

## Corrections Applied — 2026-11-07, round 1

Applied by the plan's author through `/plan-corrections`. This section is not an approval. The round 1 text above is unchanged, and only an independent reviewer can set `approved`.

All 13 findings were checked against the code and the cited primary docs first, and all 13 held. None is dismissed. Line numbers are for the corrected files: `plan` is `implementation-plan.md` and `task` is `task.md`.

| Finding | Disposition | Correction | Where | Evidence |
|---|---|---|---|---|
| F-001 | fixed | The helper starts with `#!/bin/bash -p` and runs each tool as `/usr/bin/env -i PATH=<tool path> LC_ALL=C <absolute tool>`. The Sudoers file holds the rule line and `Defaults!/opt/fleet-admin/fleet-admin env_reset, !env_keep, secure_path=...`. New A-18: before `visudo`, the setup reads `sudo -l -U <user>` and stops with no change on `SETENV`, `!env_reset` or a dangerous `env_keep` entry. New AC-26 sets `APT_CONFIG`, `BASH_ENV`, `LD_PRELOAD` and a stub-first `PATH` in the caller, and a stub `apt-get` must log none of them. The D-1 brief, its limit of A and the residual risk now state the clean environment and what it cannot cover. | plan:166-172, :173-177, :411 (AC-9), :414 (AC-26), :488-489 (step 4), :129-130, :136-140, :1089-1097 (A-18), :1105-1114, :1130-1136; task:48 (row 4) | sudoers(5) (`sudoers.man.in`): a command's `Defaults!` line applies after the general ones, `!env_keep` clears the kept list, `secure_path` replaces `PATH`, `SETENV` lets `-E` turn `env_reset` off, a matched `ALL` implies `SETENV`, and the last match wins. apt.conf(5): APT reads `APT_CONFIG` first, and `DPkg::Pre-Invoke` runs shell commands. The bash manual: `-p` reads no `BASH_ENV` or `ENV` file and imports no function. |
| F-002 | fixed | New Named definition, Key-auth check. Before password-off, `sshd -T -C user=<user>,host=<member address>,addr=<member address>` must show `pubkeyauthentication yes`, an `authorizedkeysfile` that covers the file the setup wrote, `authenticationmethods any` or exactly `publickey`, and `ssh-ed25519` in the accepted algorithms. Unix runs it as `check_key_auth` (WP-U5 step 9) and Windows as `Test-KeyAuth` (WP-U5w). The Password-off check runs it again after the change. AC-16 and AC-17 add a `pubkeyauthentication no`, a `publickey,password` and an uncovered `authorizedkeysfile` case. Each stops before the sshd config changes. | plan:187-195, :196-198, :504-505, :532 (AC-16), :559-562, :581 (AC-17), :801-802; task:50 (row 6), :51 (row 6a) | sshd(8): `-T` prints the effective config, and `-C` applies a connection spec, so `Match` blocks for that user and address apply. sshd_config(5): `PubkeyAuthentication`, `AuthorizedKeysFile`, `AuthenticationMethods` and `PubkeyAcceptedAlgorithms` decide whether a key can sign in. Today the kit turns password sign-in off with no such check. |
| F-003 | fixed | The Drop-in definition now states the Unix password-off sequence once. The setup saves a snapshot (the old bytes, owner and mode, or no file) and writes the new file. On any failure it restores the snapshot, runs `sshd -t` on it and stops with no reload. AC-16 tests a first run and a rerun with an old drop-in. Same class: step 5 now finds the unit name whether or not sshd listens, because step 10 reloads that unit. | plan:178-183, :490-492 (step 5), :506-509 (step 10), :532 (AC-16); task:50 (row 6) | `setup-unix.sh` sets the unit name only when sshd is not listening (receipt `kit-sshd-block.txt`). WP-U5w already wrote the old bytes back on Windows. |
| F-004 | fixed | In each target zone, the running branch removes the service with `firewall-cmd --permanent --zone=Z --remove-service=ssh`, then reloads. The Firewalld checks then query the rich rule (exit 0) and the `ssh` service (exit 1), at runtime and with `--permanent`. AC-15 fails a removal without `--permanent`, and AC-24 checks both states live. A-4 now covers `ufw`, `firewalld` and Windows, and names the two things that the kit replaces. | plan:205-213, :214-216, :497-498 (step 7), :531 (AC-15), :778 (AC-24), :119-122, :1019-1027 (A-11); task:50 (row 6) | firewall-cmd(1): a change without `--permanent` is runtime only, and `--reload` drops runtime changes. |
| F-005 | fixed | Step 7 now has two `firewalld` branches. Running (`firewall-cmd --state` exits 0): the rules with `firewall-cmd --permanent`, then the reload. Stopped (exit 252, `NOT_RUNNING`): the rules with `firewall-offline-cmd`, then the Listener check, then `systemctl enable --now firewalld`, then the Firewalld checks. No daemon call runs before the start. The Stub folder adds `firewall-offline-cmd` and a stopped mode in which `firewall-cmd` exits 252 until the start. Same class, found in this pass: `firewall-offline-cmd` takes no `--permanent`, and its `--remove-service` is a lokkit option for the default zone only. So the stopped branch removes the service with `--zone=Z --remove-service-from-zone=ssh`, and AC-15 fails a stopped run that uses `--remove-service=ssh`. | plan:209-213, :235-239, :499-501 (step 7), :531 (AC-15), :1019-1027 (A-11), :1176; task:50 (row 6) | firewall-cmd(1): `--state` returns `NOT_RUNNING` (252) when the daemon is stopped. firewall-offline-cmd(1): it changes the permanent config while the daemon is stopped; `--zone=<zone> --remove-service-from-zone=<service>` is the zone form; `--remove-service` is in the lokkit options and acts on the default zone; the page lists no `--permanent`. |
| F-006 | fixed | WP-U4 adds `Find-BroaderSshRule`. It lists every other enabled inbound allow rule that covers SSH (application `Any` or `sshd.exe`, protocol `TCP` or `Any`, local port `22` or `Any`) and is broader (profile `Public` or `Any`, or a remote address other than `LocalSubnet`). It prints each one by name and changes none (A-4). `check_live.py windows` uses it, and a listed rule fails AC-23. AC-13 adds a `Custom SSH` rule on `Any` beside the kit's rule. WP-U4 is now the one place that states the profile policy. | plan:442-449, :462 (AC-13), :777 (AC-23), :119-122; task:49 (row 5) | `setup-windows.ps1:72-83` manages only `OpenSSH-Server-In-TCP`. The New-NetFirewallRule and Get-NetFirewallRule docs: each allow rule applies on its own profile and address scope. |
| F-007 | fixed | WP-U6 step 3 passes only when the exit code is 0, a `GOODSIG` line is present, a `VALIDSIG` line has the key as its first or last field, and no `BADSIG`, `ERRSIG`, `EXPSIG`, `EXPKEYSIG`, `REVKEYSIG` or `NO_PUBKEY` line is present. It fails closed. AC-19 adds a revoked key, an expired key, an expired signature, exit code 1 and a second signature by an unknown key. Each must leave `Clear-Disk` uncalled. The D-2 residual risk and row 8 use the same rule. Same class: `Find-Gpg` uses the Git root that the Git bash locator finds, not a fixed path. | plan:627-637, :668 (AC-19), :142-144; task:54 (row 8) | GnuPG `doc/DETAILS`: `VALIDSIG` marks a cryptographically valid signature and can come with `EXPSIG`, `EXPKEYSIG` or `REVKEYSIG`, so it alone does not prove an accepted key state. |
| F-008 | fixed | New Named definition, Record retire. After the console guard and before any system change, the setup renames `members/<name>.json` to `<name>.json.old`. It writes a new record only after every step passes. Other members' records stay. WP-U5 step 2, WP-U5w and AC-20 use it. New AC-27 has a Unix and a Windows half: an old success record plus a CLI signature failure ends with no `<name>.json`, `import --no-test` does not list the member, and another member's record stays byte-identical. | plan:199-202, :485 (step 2), :559-560, :533 (AC-27 Unix), :582 (AC-27 Windows), :669 (AC-20), :131-132; task:50 (row 6), :51 (row 6a), :55 (row 8a) | `fleet_usb.py:74` makes `members` with `exist_ok=True` and does not empty it. `fleet_usb.py:177` globs `members/*.json`, so it never reads a `.old` file. |
| F-009 | fixed | The Git bash locator now starts from `git --exec-path` and `shutil.which("git")`. It walks up to the folder that holds `git-cmd.exe` or `usr/bin/bash.exe`, and returns the first existing `<root>/bin/bash.exe` or `<root>/usr/bin/bash.exe`. It refuses a path under `%SystemRoot%` or `%LOCALAPPDATA%\Microsoft\WindowsApps`, and it holds no fixed install path. New AC-28 tests synthetic roots with `git.exe` in `cmd/`, `mingw64/bin/` and `ucrt64/bin/`, and fails a locator source that holds a fixed user or `Program Files` path. Row 3 runs AC-28. | plan:228-234, :340 (AC-28), :1049-1058 (A-14); task:46 (row 3) | On this hub, `where bash` and the Git install folders show `git.exe` in `cmd/` and `ucrt64/bin/`, `bash.exe` in `bin/` and `usr/bin/`, and no `mingw64/`. A `parents[1]` step from `ucrt64/bin/git.exe` names a folder with no `bash.exe`. The receipt `f009-bash-layout.txt` holds a local path, so this section does not quote it. |
| F-010 | fixed | New `--privacy` mode of `check_package_gates.py` (AC-29). It scans the added lines of `git diff -U0 HEAD`, every untracked file, both plan files and the closeout artifacts. It has five classes: an email that is not `noreply` or `example.*`, an IPv4 address outside the reserved blocks, a home path with a literal name, this machine's own names and addresses, and member names or terms that the human sets. It prints only `file:line` and the class. The `--selftest` cases build one synthetic sample of each class in each file kind at run time. Rows 11 and H1-2 run it, and H2-4 runs it again after the reflection and the metrics row exist. Stop condition 12 covers a hit. | plan:758-767, :780 (AC-29), :809-810, :1196; task:58 (row 11), :65 (H1-2), :83 (H2-4) | AC-7 scans only the kit. `scripts/sanitize.py:24,53` skips `scripts/`, `.agent/context/` and `docs/execution/`. A plain `refcheck` checks references, not identity literals (receipt `f010-sources.txt`). |
| F-011 | fixed | New `--state` mode (AC-30). The state id is the SHA-256 over `git rev-parse HEAD`, each sorted inventory path with the SHA-256 of its bytes, and `sys.version`. The files that the closeout writes after H1-2 are excluded. H1-2 writes the id to `uk-state-tested.txt`, H1-6 records it as `tested_state`, and H1-6b computes it again and passes it to `--expected-state`. The AC-30 selftest makes a second byte change to a file that is already modified and requires a new id. | plan:752-757, :781 (AC-30), :1200-1206; task:65 (H1-2), :69 (H1-6), :71 (H1-6b) | `core/tools/durable_evidence.py:131-136` compares `--expected-state` with `tested_state`. A byte change in a file that is already modified leaves HEAD, `git status --porcelain` and `sys.version` the same. |
| F-012 | fixed | H2-3b now renders with `python core/tools/issue_triage.py --yaml .agent/context/known-issues.yaml --md .agent/context/known-issues.md render`, and `render --check` uses the same two paths. The validation first requires the new issue id in both files. | task:81 (H2-3b) | `core/tools/issue_triage/model.py:23-26` sets the defaults to `core/.agent/context`. `core/tools/issue_triage.py:368-377` reads `--yaml` and `--md` as global options before the subcommand. The H2-3b dry run fails before the issue is filed. |
| F-013 | fixed | No "default if unanswered" wording remains. D-1 and D-2 stay human decisions, with A as the recommendation first, and their `chosen:` lines read `pending`. New row 3a records the human's typed D-1 ruling, and row 4 depends on it. New row 7a records the typed D-2 ruling, or `not applicable` when row 0 discards the CLI step, and row 8a depends on it. Each of the two validations passes only on a `chosen:` line that holds `USER_EXPLICIT` and does not start with `pending`. A ruling other than A sends that row back to planning (stop condition 11). H1-6 records the typed rulings. | plan:101-104, :807-808, :899-918, :1101, :1113-1114, :1144-1145; task:35, :47 (row 3a), :48 (row 4), :53 (row 7a), :55 (row 8a), :69 (H1-6), :103-104 | The planner brief and PR-1: D-1 and D-2 are human decisions. `census-final.txt`: 0 sites for "efault if unanswered", "unless the human rules otherwise", "under D-1 A", "under D-2 A" and "Under D-". The dry runs: rows 3a and 7a fail on the pending plan and pass only on a typed ruling. |

Advisories folded in:

- PC's no-commit branch (task:41): the row is `[x] n/a` when no commit is directed. Its validation passes on an untracked plan only when `task.md` has no `run_parameters` block. The dry run prints `n/a: no commit was directed`.
- The exclusion label (round 1 plan:666, now plan:819): the `setup-member.ps1:41` row is `out-of-scope`, with the follow-up known issue `FLEET-SETUP-MEMBER-UNVERIFIED-INSTALLERS` that H2-3b files.
- The console-walk bound: the Console guard definition (plan:261) is the one statement, and both AC-14 halves refer to it (plan:530, :580).
- The firewall profile set: WP-U4 (plan:442) is the one statement, and the other sections refer to it.
- The password policy: the Drop-in definition (plan:178-183) and the Marked block definition (plan:184-186) hold each OS sequence. WP-U5 step 10, WP-U5w and AC-16 refer to them.
- The helper permissions: the Helper definition (plan:166-167) is the one statement of owner and mode, and AC-9 refers to it.

Conflicts, flagged and not resolved here:

- `core/.agent/workflows/plan-corrections.md:245-247` tells the corrections agent to set the frontmatter `verdict:` to `corrections_applied`. The planner brief forbids any frontmatter change. This section follows the brief. The frontmatter still reads `changes_required`, and the Status column above still reads `open`.
- `core/.agent/workflows/create-plan.md:209` and `:559` and `core/templates/PLAN-TEMPLATE.md:203` and `:226` define a "Default if unanswered" field for a Decision Brief. The same wording is in `core/.agent/docs/issue-lifecycle-guide.md:165`, `core/.agent/workflows/delegated-plan-creation.md:354`, `execution-session.md:214`, `issue-triage.md:174`, `next-project.md:219` and `core/.agent/skills/cli-dispatch/SKILL.md:403`. F-013 and the planner brief override it for this plan only. Those files are not changed. Receipt: `default-wording-sites.txt`.

**Open human decisions:** D-1 (row 3a) and D-2 (row 7a). Both are pending, and A is the recommendation for both. This pass adds no new human decision. A-18 and the stock `ssh` service replacement (A-10) are two-way, and User Review Required flags both (plan:119-122, :129-130).

**Blast-radius census:** 24 values swept over both plan files. 11 old values now have 0 sites. The other 13 values have 41 sites, and each site was read and is consistent. Receipts: `C:/Temp/zorivest/usb-kit-plan/corrections-r1/census-final.txt` and `census-residue.txt`.

**Verification:** `lint_task_contract.py` passes with 43 rows (`lint-final.txt`). The 10 dry runs of the new row validations against synthetic receipts all behave as specified (`dryrun-rows-final.txt`). The privacy scan of both plan files and this file finds 0 hits, and its selftest finds all 6 synthetic samples (`privacy-final.txt`, `privacy-selftest.txt`). No AC was executed, because every correction is plan text and the tests do not exist yet. All receipts are in `C:/Temp/zorivest/usb-kit-plan/corrections-r1/`.

Corrected input SHA-256 values (`implementation-plan.md` has 1206 lines; `task.md` has 108 lines and 43 rows):

- `implementation-plan.md`: `923b3072362d352005de4857e785bf58dc22258d287b8247ab0c812c975aa35e`
- `task.md`: `8c360b11e10ded5b6bd8131e82cfe58226cc28fcb751c8dd4b519ac5e8abf9fa`

🕐 Completed: 2026-11-07 12:36 (EST)

## Recheck (2026-11-07) — Round 2 of 3

**Workflow:** `/plan-critical-review`  
**Agent:** Codex  
**Verdict:** `changes_required` — PR-6 procedural precondition only; no delivery-level severity assigned.

**Intent anchor:** Executing this plan should close the seven kit findings while preserving administrative access, limiting privilege and network exposure, verifying downloads, and supplying usable tests and public documentation. This round cannot determine whether the corrected plan delivers that objective because the protocol's resubmission evidence gate fails before substantive review.

### Procedural finding

**F-014 — Incomplete correction blast-radius census.** Confidence: High. This is the sole round-2 blocker, under `core/.agent/workflows/plan-critical-review.md:256` and `:287-291`, rather than a severity-rated defect in the kit design.

The correction log at `.agent/context/handoffs/2026-11-07-usb-kit-hardening-plan-critical-review.md:497` supplies a collective assertion that all 41 sites are consistent, without assigning `updated` or `confirmed-consistent` to each `file:line`. The finding-level correction table at :465-479 maps findings to selected locations; it does not disposition each census hit. The stated protocol expressly says a bare count is insufficient and that the correction log and raw receipt must both exist.

The two named receipts also do not provide the required raw matching text:

- `receipt file C:/Temp/zorivest/usb-kit-plan/corrections-r1/census-final.txt`, lines 1-26, lists patterns, counts and locations, but omits the matching source text. For example, line 7 lists eight `--remove-service` sites without their payloads.
- `receipt file C:/Temp/zorivest/usb-kit-plan/corrections-r1/census-residue.txt`, lines 1-14, supplies only seven selected excerpts. Several are visibly clipped mid-line; it is not the full set of matching source lines.

**Attempted refutation:** The corrections table does contain individual F-001 through F-013 dispositions, and the census summary names locations rather than just totals. Other scratch receipts, including `census-sites.txt`, were checked for a substitute per-hit log. None supplies per-hit `updated` / `confirmed-consistent` dispositions for the final census. Even a complete alternative raw sweep would not repair that independently missing correction log. This conclusion does not allege forged evidence or distrust the human's plan-to-execution reading.

**Failure caused:** The resubmission cannot establish the correction blast radius required to enter the substantive recheck. PR-6 explicitly directs the reviewer to return `changes_required` naming this alone and **not review the corrected content this round**. Applying that instruction is why this round does not issue new security findings, approve corrections, or classify them as partly fixed.

**Required correction:** Preserve unfiltered, untruncated old/new and semantic-variant sweeps of both plan files, including each matching line's text and exit result. Append a correction-log map that assigns every receipt `file:line` either `updated` or `confirmed-consistent`, with old-to-current locations where necessary. Keep zero-hit searches explicit. Submit that evidence through `/plan-corrections` before another independent recheck. No kit-code change is requested by F-014.

### Prior Pass Summary

All results below are deliberately **unverified**, not assertions that a correction failed. The planner reports every item fixed; PR-6 prevents independently checking those claims this round. The references identify the planner's claims only.

| Finding | Planner report | Round-2 result | Claim location in this file |
|---|---|---|---|
| F-001 | fixed | Unverified — PR-6 gate | :467 |
| F-002 | fixed | Unverified — PR-6 gate | :468 |
| F-003 | fixed | Unverified — PR-6 gate | :469 |
| F-004 | fixed | Unverified — PR-6 gate | :470 |
| F-005 | fixed | Unverified — PR-6 gate | :471 |
| F-006 | fixed | Unverified — PR-6 gate | :472 |
| F-007 | fixed | Unverified — PR-6 gate | :473 |
| F-008 | fixed | Unverified — PR-6 gate | :474 |
| F-009 | fixed | Unverified — PR-6 gate | :475 |
| F-010 | fixed | Unverified — PR-6 gate | :476 |
| F-011 | fixed | Unverified — PR-6 gate | :477 |
| F-012 | fixed | Unverified — PR-6 gate | :478 |
| F-013 | fixed | Unverified — PR-6 gate | :479 |

No round-1 finding is reopened, dismissed or independently marked fixed. The helper environment, key-auth checks, rollback, firewall branches, signature policy, record retirement, locator, privacy/state gates, render paths and all 43 task rows remain for substantive recheck once PR-6 is satisfied. D-1 and D-2 remain the human's typed decisions; this review chooses neither and supplies no default or execution authorization.

### Evidence and Checklist Results

The protocol, the full correction section, both named census receipts and the alternative census summaries/excerpts were read. Searches for `disposition`, `confirmed-consistent`, `updated` and `census` across the corrections receipts and rolling review found no final per-hit disposition log. No public documentation fetch, test suite, linter or parse check was needed to resolve this procedural precondition; none is claimed as run this round.

| Check | Result | Procedure | Exit | Evidence |
|---|---|---|---|---|
| PR-6 correction census | fail | Read both named receipts in full; compare correction section and alternative census files with protocol PR-6 and corrections Step 5c; observer Codex | null, manual | Final summary gives 24 searches and 41 sites without matching text; correction log gives no per-hit dispositions. Selected residue excerpts are clipped. |
| PR-1 through PR-5, PR-7 through PR-9 | n/a | Not reached: mandatory pre-verdict gate | n/a | No substantive round-2 conclusions. |
| DR-1 through DR-8 | n/a | Not reached: mandatory pre-verdict gate | n/a | No implementation or correction correctness/freshness approval. |
| Review scope preservation | pass | Read-only git status and SHA-256 snapshots; observer Codex | 0 for commands | Only this canonical review is edited; scratch output remains in the authorized folder. No member, hub, SSH or remote service contacted. |

```json
{"schema_version":"evidence.v1","check_id":"R2-PR6-precondition","command":null,"procedure":"Read plan-critical-review PR-6 and Verdict Rule, plan-corrections Step 5c, correction log lines 459-506, census-final.txt and census-residue.txt in full; inspect alternative census files and search all correction receipts for a per-hit disposition log.","observer":"Codex","cwd":"P:/agentic-framework","scope":"round-2 correction evidence precondition only","phase":"manual","exit_code":null,"result":"fail","output":"Named final receipt: 24 patterns, 41 sites, no matching source payloads. Residue: seven selected excerpts with clipped lines. Correction log: collective consistency claim and per-finding table, no per-hit updated/confirmed-consistent map. PR-6 prohibits substantive corrected-content review this round."}
```

Input hashes match the planner's corrected input hashes:

- `implementation-plan.md`: `923b3072362d352005de4857e785bf58dc22258d287b8247ab0c812c975aa35e`
- `task.md`: `8c360b11e10ded5b6bd8131e82cfe58226cc28fcb751c8dd4b519ac5e8abf9fa`

Scratch evidence is under `review receipts C:/Temp/zorivest/usb-kit-plan/review-r2/`: `pr6-precondition.txt`, `input-hashes.txt` and `stamp.txt`. The decisive evidence is reproduced above so the verdict remains interpretable without scratch files.

### Verdict

**changes_required** — F-014 is a precondition failure, using the workflow's explicit procedural exception. This is round 2 of 3. No conclusion is reached about whether executing the corrected plan achieves the intent; no substantive correction is certified or rejected. Restore the census evidence and request the next independent review. No plan, kit, fleet, test or documentation file was changed, and no Git write or commit was performed.

The v1 structured schema requires a severity field even for this procedural exception. Its F-014 `Low` field is a transport placeholder only, not a delivery-level severity judgment or the reason for this verdict; PR-6 is the reason.

🕐 Completed: 2026-11-07 12:43 (EST)

## Corrections Applied — 2026-11-07, round 2

Applied by the plan's author through `/plan-corrections`. This section is not an approval. All earlier text in this file is unchanged, except the frontmatter `verdict:` value, which `plan-corrections.md:245-247` sets to `corrections_applied`. Only an independent reviewer can set `approved`.

This pass covers F-014 of round 2 and an advisory read that was done before round 3 (`C:/Temp/zorivest/usb-kit-plan/peer-r2/findings.md`). The advisory read is not a review round. All 20 items were checked against the code and the primary docs first, and all 20 held. None is dismissed. Line numbers are for the final files: `plan` is `implementation-plan.md` and `task` is `task.md`.

| Item | Disposition | Correction | Where | Evidence |
|---|---|---|---|---|
| F-014 | fixed | A new census replaces the round 1 claim of 41 consistent sites. A script runs `rg` for each value over the final text, and for each old value over the round 1 and round 0 text too. The receipt holds each matching line in full, its file:line and the search's exit code. An empty search stays as an explicit entry. The map gives each hit `updated` or `confirmed-consistent`, with the hit's line in each round. | See "Blast-radius census" below | `plan-critical-review.md:256` (PR-6); `plan-corrections.md` Step 5c. `census_verify.py` is a separate check. It compares each receipt hit with the whole file line, each exit code with its hit count, and the receipt set with the map set. |
| F-002 (partly closed) | fixed, with N3 | The Key-auth check existed but could pass while key sign-in fails. N3 gives the change. | plan:206-233 | N3 |
| F-005 (partly closed) | fixed, with N1 | The stopped branch used `firewall-offline-cmd`, but the zone pick read only the permanent config. N1 gives the change. | plan:254-272 | N1 |
| F-006 (partly closed) | fixed, with N5 | `Find-BroaderSshRule` existed but missed rule forms and the Group Policy store. N5 gives the change. | plan:526-545 | N5 |
| N1 | fixed | Target zones now come from the runtime: `--get-zone-of-interface` with no `--permanent`, else `--get-default-zone`. The stopped branch takes its first zones from `firewall-offline-cmd`, and the setup resolves the runtime zones again after the start. A zone that shows only then gets the running-branch pass. After the pass, a member interface in a zone outside the target set stops the setup. AC-15 adds three zone cases, and AC-24 checks the runtime zones live. | plan:254-257, :263-268, :269-272, :155-156, :644 (AC-15), :911 (AC-24), :1160 (A-11); task:50 (row 6) | firewalld, "Connections, Interfaces and Sources": NetworkManager assigns the connection's interface to its zone before the interface is used, and with no zone set it goes to the default zone. firewall-cmd(1): `--get-zone-of-interface` and `--permanent`. firewall-offline-cmd(1): for use only when the service is not running, and it reads only the config folders. |
| N2 | fixed | A-18 now reads the three sections of `LC_ALL=C sudo -l -U <user>` and compares whole tokens. The kit's own `Defaults!` line passes, in its written form and in the form sudo prints, so a rerun passes. Stock `env_keep` names pass, so a stock machine passes. AC-26 lists each stop case and each pass case. Rows 13 and 14 feed each member's real `LC_ALL=C sudo -n -l` output through the parser. | plan:1230, :1233-1234 (A-18), :489 (AC-26), :477, :635, :1269-1279; task:48 (row 4), :60, :61 | `display.c:467`, `:485`, `:503`: the three headers. `fmtsudoers.c:294-308` and `parse.h:27`: quotes only for a value with a space, and a backslash before each colon. sudoers(5): `Defaults!` applies last. `sudo.man.in:770-786`: `-U` needs root or list rights, so the hub's account uses `-l`. Limit: the stock Ubuntu, Fedora and macOS samples are written from the sources and not from a live machine, so the live rows check them (plan:1234). |
| N3 | fixed | The check now runs once for each member address, with `laddr=` and `lport=22` in the spec, and compares whole tokens. `authorizedkeysfile` is split on whitespace. `ssh-ed25519` must be one comma-separated token, so a list with only the certificate type fails. New Account filters cover `denyusers`, `denygroups`, `allowusers` and `allowgroups`, and fail closed where the setup cannot prove a match. New Strict modes apply upstream's rule to the home, `.ssh` and `authorized_keys`. The `from=` limit is stated, and setup prints the subnets for the human to compare. | plan:206-233, :152-154, :645 (AC-16), :700 (AC-17), :910 (AC-23); task:50, :51, :59 (row 12) | sshd_config(5): "USER and HOST are separately checked"; DenyUsers and DenyGroups take precedence; AuthorizedKeysFile takes several files or `none`. sshd(8): `-T` checks the config file and prints the effective config; `-C` and its criteria; `from=` is a key option in `authorized_keys`. OpenSSH `misc.c` `safe_path()`: `st_mode & 022`. Limit: the hub has no `sshd.exe` (`hub-openssh-ls.txt`), so the printed `__PROGRAMDATA__` form is not verified. Both forms pass, and row 12 captures the real text. |
| N4 | fixed | The preflight now joins `Get-NetConnectionProfile` to `Get-NetAdapter -Physical` on `InterfaceIndex` and applies the kit's `^vEthernet` filter. A Public network on a counted adapter stops the setup, and so does no Private or Domain network on one. A Public network on another adapter is printed and does not stop. | plan:515-522, :127-129, :567 (AC-13), :1200-1204 (A-15), :934-935 (stop 6); task:49 (row 5), :59 | `setup-windows.ps1:108-110` already leaves out `^vEthernet`. Get-NetAdapter: `-Physical`. Get-NetConnectionProfile: `InterfaceIndex` and `NetworkCategory`. Limit: a guest machine's adapter is physical from the guest's view, and row 12 confirms that on its guest. |
| N5 | fixed | `Find-BroaderSshRule` now reads `-PolicyStore ActiveStore`. A local port can be a list entry or a range, the service filter counts, and the protocol can be `TCP`, `6` or `Any`. A remote entry is compared with the member's subnets, so a narrow rule is not listed. A same-named Group Policy rule with a broader scope is listed. An off profile is reported. Row 12 runs the report over SSH through `-EncodedCommand`. | plan:526-545, :567 (AC-13), :910 (AC-23), :1093 (A-4); task:49, :59 | Get-NetFirewallRule: with no store it reads the persistent store; ActiveStore is the sum of all stores. Get-NetFirewallPortFilter, Get-NetFirewallServiceFilter and Get-NetFirewallProfile: their ActiveStore forms; a rule with no service matches any service. New-NetFirewallRule: the `-LocalPort` and `-RemoteAddress` forms and keywords. |
| N6 | fixed | The Listener check now reads `ss -ltnuH`, parses the Netid column, removes `%<interface>` and takes the port after the last colon. A non-loopback UDP socket stops the setup, port 22 included, unless the firewall being enabled keeps that port open. The kept ports are listed for each tool. | plan:246-253, :630, :644 (AC-15), :911 (AC-24), :1160, :1164 (A-11); task:50, :60 (row 13) | ss(8): `-l -t -u -n -H`. iproute2 `ss.c`: `UNCONN`, the `Netid` column and `addr%ifname`. udp(7): connectionless. ufw `before.rules` and `before6.rules:133,136,139`. firewalld `public.xml`: SSH and DHCPv6 client only. Limit: `main()` of `ss.c` could not be read, and UDP 68 under `firewalld` is not in `public.xml`. Row 13 captures the real output. |
| N7 | fixed | A failure before the reload restores the snapshot and makes no reload. A failed reload restores it and reloads once more. After a reload passes, a later failure keeps the drop-in, so the file and the running sshd agree. The Marked block has the same rule on Windows. | plan:193-201, :202-205, :1210, :1214 (A-16), :645 (AC-16), :700 (AC-17); task:50, :51 | sshd(8): sshd rereads its config on SIGHUP, so after a reload it already uses the new file. |
| N8 | fixed | Each parent folder of the helper up to `/`, on the physical path, must have owner 0 and no group or other write bit. `install_helper` and the helper's self-check both run the walk. The D-1 brief now states this. | plan:176-179, :458, :486 (AC-9), :487 (AC-10), :1280-1283, :934-935 (stop 6); task:48 | The round 1 plan checked only the file and its folder. A writer of a parent can rename the folder and put a script at the sudo path. OpenSSH's `safe_path()` walks parents for the same reason. |
| N9 | fixed | New Mode reader: `stat -c '%u %g %a'` on Linux and `stat -f '%u %g %Lp'` on macOS, picked by `uname -s`. The Helper, the Drop-in snapshot and the Key-auth check use it. The Stub folder adds `uname`. | plan:185-187, :312-313, :486 (AC-9), :645 (AC-16) | GNU stat(1): `-c`, `%a`, `%u`, `%g`. FreeBSD stat(1): `-f`, and `L` gives the user, group and other bits of a numeric `p`. Both are saved in `fetched/`. Row 14 runs the BSD form on macOS through the helper's self-check. |
| N10 | fixed | `--privacy` now diffs against the baseline HEAD that row 1 stores, so a mid-plan commit drops no line. It allows `198.18.0.0/15` and `224.0.0.0/4`. The human can set `$env:UK_PRIVACY_ALLOW` for a value that is also a common word; the scan prints only the skip count. Same class, found in this pass: the email class also hit `ssh-ed25519-cert-v01@openssh.com`, so the plan's own gate would have failed on N3's text. `openssh.com` is now allowed, and AC-29 tests that name. | plan:886-899, :890-891, :913 (AC-29), :944-946 (stop 12); task:43 (row 1) | RFC 2544 and RFC 5771: neither block is a LAN range. sshd_config(5) lists algorithm names in that form. The first privacy scan of this pass reported plan lines 218 and 645 (`privacy-preappend.txt` holds the rerun). |
| N11 | fixed | AC-26 now names what the test can assert. A static test reads `main` for the fixed tool path, and the test sets its own tool path to the stub folder. Stubs log with bash builtins, because the helper gives them an empty environment and only the tool path. Same class, found by measurement in this pass: the allowed log names were incomplete, and a missing `LD_PRELOAD` path kills Git bash. AC-26 now lists the exact names and sets the value to `/usr/bin/msys-2.0.dll` under Git bash. | plan:489 (AC-26), :183-184, :307-314 | Run on the hub's Git bash. A stub under `env -i` logs `DEBIAN_FRONTEND LC_ALL MSYSTEM OLDPWD PATH PWD SHLVL SYSTEMROOT WINDIR` (`env-i-stub-names.txt`). The same log comes with `LD_PRELOAD=/usr/bin/msys-2.0.dll` (`env-i-stub-dll-names.txt`). A missing path exits 129 with a fatal error (`env-i-stub-preload-missing.txt`). `bash -p` does not read `BASH_ENV`, and plain `bash` does (`bash-p-gitbash.txt`). |
| N12 | fixed | The running branch runs each change at runtime and with `--permanent`, each after its own query. It never runs `--reload` or `--runtime-to-permanent`. AC-15 fails any `--reload` call. | plan:261-263, :606-608, :644 (AC-15), :155-156, :1150, :1154 (A-10), :1322; task:50 | firewall-cmd(1): with `--reload`, "all runtime only changes done until reload are lost"; `--runtime-to-permanent` overwrites the permanent config with the runtime one. firewalld concepts: separate runtime and permanent configs. |
| N13 | fixed | The new Broad-rule report covers `firewalld` port `22/tcp`, ranges, custom services, rich rules, target `ACCEPT` and other active zones with a source binding, and `ufw` names and ranges. A rule on a range that leaves out 22 is not listed. It reads and never deletes. | plan:273-281, :634, :644 (AC-15), :911 (AC-24), :1093 (A-4); task:50 | firewall-cmd(1): `--query-port`, `--list-ports`, `--list-services`, `--info-service`, `--list-rich-rules`, `--get-target`. A-4 stays: report, do not delete. |
| Low note on F-008 | fixed | Record retire now also retires, and prints, any other `members/*.json` whose `host_key` equals this machine's key, when that key file exists. A machine with a new key leaves its old-name record, and `import` reports that record as a failed or changed-key connection. | plan:237-245, :134-135, :646, :701 (AC-27), :1170 (A-12) | `setup-unix.sh:134-136`, `setup-windows.ps1:103-106`, `fleet_usb.py:177`, `:195-198`. A clone that shares the key retires its twin's record; the line is printed and the rename is reversible. |
| Low note on F-009 | fixed | `Find-Gpg` takes `PATH` first, then `Find-GitRoot`, which applies the one Git root rule in PowerShell. AC-19 tests it on the same synthetic layouts as AC-28. | plan:297-306, :790 (AC-19), :415 (AC-28), :1220-1224 (A-17); task:54 (row 8) | The kit cannot call a Python test helper, so the rule has two implementations, and a drift fails a test. |
| Low note on F-013 | fixed | Rows 3a and 7a now pass only when `USER_EXPLICIT` is present and the ruling starts with `A `. Any other ruling fails the row and sends that work back to planning. Row 7a keeps its `not applicable` path for a discarded CLI step. | task:47, :53, :35, :104; plan:942 (stop 11) | `dryrun-rows.txt`: typed B, typed C, A with no `USER_EXPLICIT`, `A2` and `USER_EXPLICIT` with no option each fail on both rows. Typed A passes on both. |

Same-class fixes found in this pass, beyond the ones in the rows above:

- `NOSETENV: ` holds `SETENV: ` as a substring, so A-18 compares tags as whole tokens (plan:1230, :489; `fmtsudoers.c:270`).
- sudo translates its headers, so each read sets `LC_ALL=C` (plan:477, :635, :1230; `display.c:467`).
- The not-allowed line hides every Defaults line. The setup reads again right after `install_sudoers` and removes that file on a stop (plan:1230, :1273-1274; `display.c:519`).
- A `Defaults!` line can bind several commands, so A-18 checks each member, `ALL` and aliases (plan:1230, :489; `display.c:386`).
- Output with no known header stops the setup (plan:1230, :489).
- Source tags. `Human-approved (advisory ...)` is gone, because the human has not seen the advisory read. It now reads `cases from the advisory read`, and each row keeps a valid tag (plan:486, :489, :567, :644-646, :700-701, :790, :911, :913).
- A-16's chosen text now says "before any sshd config change" (plan:1210).
- AC-14's Windows half now names `sshd-session.exe` and `wsmprovhost.exe`, because the text stopped naming the first in round 1 (plan:338, :699).
- Row 1 stores HEAD in its baseline (task:43; plan:887-888).

The advisory read also tested two possible defects and refuted them: a missing `--baseline`, and AC-2 `agy` hits outside `fleet.py`. No change was needed. It finds F-001, F-003, F-004, F-007, F-010, F-011 and F-012 closed, and F-008, F-009 and F-013 closed with the Low notes above. This pass does not reopen any of them.

Conflicts:

- The round 1 section flagged a conflict about the frontmatter `verdict:` value. The coordinator's round 2 instruction settles it: `plan-corrections.md:245-247` applies. The round 1 text stays as it was written.
- The "Default if unanswered" conflict in the round 1 section is still open in those workflow files. Nothing in this pass changes them.
- D-1 and D-2 carry `source_tag: Human-approved` with `chosen: pending` (plan:1040-1041, :1050-1051). `create-plan.md:163` says that tag means a decision that the user resolved, but the schema at `human-decision-protocol.md:239` has no value for a pending human decision. This pass leaves the tag as it is. Neither entry has a `human_message_reference`, and rows 3a and 7a read `chosen`, not the tag, so the tag cannot pass either row. The human or the reviewer can rule on it.

**Open human decisions:** D-1 (row 3a) and D-2 (row 7a). Both are pending, and A is the recommendation for both. This pass adds no new human decision. The D-1 brief changed: the sudoers policy limit (plan:1269-1279) and the helper's path (plan:1280-1283). The D-2 brief needed no change. The plan states three stricter behaviours from this pass, so the human can see them: Strict modes can stop a setup that a distro patch would have allowed (plan:224-227), a clone retires its twin's record (plan:241-242), and a general `env_keep` stop is stricter than sudoers needs (plan:1234).

**Blast-radius census:** 407 values changed, 31 variants swept, 1460 sites found, 1402 updated, 58 confirmed consistent.

The 438 declared values are 62 old, 345 new and 31 variants. 178 are declared by hand and 260 come from the code spans that a script derived from the diff (`derived-values.txt`). The script ran 562 searches.

| Class | Target | Searches | Hits | Updated | Confirmed consistent | Zero-hit |
|---|---|---|---|---|---|---|
| old | final | 62 | 49 | 49 | 0 | 42 |
| old | round 1 | 62 | 71 | 59 | 12 | 25 |
| old | round 0 | 62 | 54 | 54 | 0 | 29 |
| new | final | 345 | 1026 | 1022 | 4 | 0 |
| variant | final | 31 | 260 | 218 | 42 | 3 |
| **Total** | | **562** | **1460** | **1402** | **58** | **99** |

- Disposition. For a final hit, `updated` means the line differs from round 0, and the map names the pass that changed it. `confirmed-consistent` means the line is the same as in round 0 and was read against the corrected text. For a round 1 or round 0 hit, `updated` means the line changed or left, and the map gives its final line, or `removed`. `zero-hit` rows keep the empty searches.
- The 49 old-value hits in the final text each have a reason in the map's last column. The script marks a hit `UNRESOLVED` unless a rule covers each occurrence on the line, and `census_verify.py` fails on that mark. Unresolved: 0.
- The three zero-hit variants are `D-2 A`, `default if` and `Default if`.
- Each of the 214 distinct final lines on the read list was read: each old or variant hit, and each confirmed-consistent hit of any class.
- Round 0 text. This file states no hash for it, so the rebuilt text cannot be compared with a stated value. The script rebuilt it from the plan author's Read results: 1015 lines with sha256 `0e698e18bd1be660dcd3f8d4c8603946f4d15db49430b18c9cb62efb2a5feda9`, and 107 lines with sha256 `cddf85170871033cb13104da263e3e7f30823cde70e2743556e6fc71d3de3e53`, with no line missing. The round 1 snapshot does match the hashes in the round 1 section.

Receipts, all in `C:/Temp/zorivest/usb-kit-plan/corrections-r2/`:

- `census-receipt.txt`: every search, its exit code and each matching line in full.
- `disposition-map.txt`: one row per receipt hit, with the zero-hit rows.
- `census-summary.txt`, `derived-values.txt`, `read-list.txt`, `read-delta.txt` and `census-verify.txt`.
- `before/` (round 1 text) and `r0/` (round 0 text).
- `fetched/` (the sudo sources, `stat` pages and sshd pages).

**Verification:** `census_verify.py` passes (`census-verify.txt`: searches 562, hits 1460, map rows 1460, zero-hit 99). `lint_task_contract.py` passes with 43 rows (`lint-final.txt`). `final_checks.py` finds AC-1 to AC-30 with none above 30, and WP-U5 with 12 steps (`final-checks.txt`). The 23 dry-run cases of rows 1, 3a, 7a, PC and H2-3b all behave as specified (`dryrun-rows.txt`). Rows 1, 3a and 7a are the only rows with a `python -c` snippet that changed. Rows 4, 5, 6, 6a, 8, 12, 13 and 14 changed in their task text, and their validation calls files that do not exist yet, so only the lint covers their form. The privacy scan of both plan files and this file finds 0 hits, and its selftest finds all 6 synthetic samples (`privacy-final.txt`, `privacy-selftest.txt`). No AC was executed, because every correction is plan text and the tests do not exist yet.

Corrected input SHA-256 values (`implementation-plan.md` has 1361 lines; `task.md` has 108 lines and 43 rows):

- `implementation-plan.md`: `c31633e29f10e06ef41f4bdaba908c4f727306c89aafe3c9ea3c3b179825c494`
- `task.md`: `39a9bf49435f3adb8ddeae419af8b3ec4142577e688f7f4953e45f8443f96e49`

🕐 Completed: 2026-11-07 14:32 (EST)


## Recheck (2026-11-07) — Round 3 of 3

**Workflow:** `/plan-critical-review`  
**Agent:** Codex  
**Verdict:** `changes_required` — five High findings require correction before execution. This is the last permitted review round. Round 2 reviewed no corrected content, so this is the first substantive recheck.

**Intent anchor:** Executing this plan should close the seven kit findings while keeping a usable administrative connection, reducing privilege and network exposure, verifying downloads, and supplying tests and public documentation. The corrections remove the original concrete failures, but the new policy parser, firewall checks and conditional CLI branch still permit the delivery failures below.

### Findings

Confidence is High for every finding. These are conditional counterexamples to the specified plan, not claims about any live member. The human’s reading at the plan-to-execution gate is the trust anchor; no counterexample depends on author forgery.

| Finding | Severity | Blocking before execution | Kind / mechanism | Evidence and failure |
|---|---|---|---|---|
| F-015 | High | yes | control-defeat; `unrecognized-command-default-bypasses-startup-environment` | `implementation-plan.md:1230`, `:188-192`, `:1269-1279`: the parser’s exact helper/ALL/alias selector test does not cover a wildcard or directory that sudo applies to the helper. A `setenv` default can therefore reach the interpreter startup boundary. |
| F-016 | High | yes | behavior | `implementation-plan.md:254-272`, `:276-279`, `:607-619`: interface-zone rules and checks can all pass while a source-bound `drop` zone receives and drops the intended SSH traffic. The first start changes a working reachable service into an unreachable one. |
| F-017 | High | yes | behavior | `implementation-plan.md:246-253`, `:603-604`, `:644`, `:1160-1164`: port-only UDP exceptions can approve enabling a firewall that blocks an existing unicast listener. The new guard does not deliver A-11’s safe-enable contract. |
| F-018 | High | yes | control-defeat; `broader-source-rule-omitted-from-report` | `implementation-plan.md:273-280`, `:601-604`, `:634`, `:911`, `:1090-1094`: the UFW report only accepts `Anywhere`, omitting a larger source subnet that still exposes SSH beyond the member subnets. A-4’s required warning is missing. |
| F-020 | High | yes | control-defeat; `unix-only-retention-skips-windows-decision-and-verification` | `task.md:42`, `:53`, `:55`; `implementation-plan.md:767-776`, `:869-870`; current `setup-windows.ps1:28-44`, `:98-100`: the Windows CLI installer can survive row 0 while the Unix-only flag makes D-2 and binary verification inapplicable. |
| F-019 | Medium | no | behavior | `implementation-plan.md:185-187`, `:224-227`, `:645`; current `setup-unix.sh:94-103`: the new Mode reader examines a symlink itself, so the claimed upstream Strict modes check refuses a secure linked `.ssh` directory. This is a compatibility refusal, not a privilege escalation. |

All plan references in this section are inside `docs/execution/plans/2026-11-07-usb-kit-hardening/`. Kit code references are inside `.agent/fleet/usb/`. Recommendations and attempted refutations follow.

#### F-015 — A-18 does not implement sudo’s command matching

Consider an existing command-specific `Defaults!/opt/fleet-admin/* setenv` entry. A-18 only stops for the exact helper path, `ALL`, or an uppercase alias, so the wildcard is not caught on either read. A directory selector `/opt/fleet-admin/` has the same problem. These forms match the helper under sudo’s command semantics. No broader command grant is needed: the kit’s own command grant supplies the permission.

**Attempted refutation:** `bash -p` blocks shell startup files/functions, and `env -i` correctly protects package-manager children. Neither executes before the root interpreter’s dynamic loader. A `setenv` permission admits a command-line `LD_PRELOAD` assignment; a caller-controlled library can execute before the helper performs any check. The two Boolean admin probes still report `full=False`, `helper=True` for an account allowed only this helper. This differs materially from F-001’s original `APT_CONFIG` reaching `apt-get`: that child-environment route is fixed; the newly added selector parser misses a root-interpreter route.

**Sources:** [sudoers command matching and environment policy](https://raw.githubusercontent.com/sudo-project/sudo/main/docs/sudoers.man.in), [sudo’s environment-validation branch](https://raw.githubusercontent.com/sudo-project/sudo/main/plugins/sudoers/sudoers.c), [the loader’s startup behavior](https://man7.org/linux/man-pages/man8/ld.so.8.html). The plan schedules `check_sudo_policy`, but it does not exist yet; this review models its stated selector rule and does not claim to have executed an implementation or an exploit.

**Required correction (PR-4, PR-8; finding 1):** establish the effective startup environment with sudo-native enforcement. An explicit `NOSETENV` policy can reduce dependence on the parser, but also account for other applicable command-specific environment overrides. If a parser remains, an unproved selector must not be treated as unrelated. Add wildcard/directory and pre-interpreter negative cases. Correct D-1’s boundary description at the same time. This is a concrete complexity failure: the hand-written parser recognizes fewer command selectors than the policy engine it tries to validate.

#### F-016 — Interface zones do not determine every packet’s zone

Take a stopped firewalld configuration whose member interface belongs to `public`, with an equal-priority source binding for the hub’s subnet in `drop`. The planned offline and running passes install the SSH allow only in `public`. The runtime interface-zone checks then correctly say `public`, the rich rule is present there, and its stock SSH service is absent.

**Attempted refutation:** N1 correctly fixes runtime NetworkManager bindings. N13 also visits source-bound zones, but only to report broader accepts; a `drop` target supplies none. With equal priorities, source classification precedes interface classification. The hub’s TCP packet is dropped before the interface-zone allow can help. The TCP-22 listener exception permits the first start, so discovery by the later import is too late to preserve the promised access order. This is a classification failure, not the already-fixed stopped-daemon command error in F-005.

**Sources:** [firewalld zone priorities and legacy classification order](https://firewalld.org/2023/04/zone-priorities), [the stock drop zone](https://raw.githubusercontent.com/firewalld/firewalld/main/config/zones/drop.xml). Current `setup-unix.sh:54-63` has no firewalld path; the new path is explicitly scheduled in task row 6.

**Required correction (PR-4; Goal finding 3, A-11/A-12):** inspect source bindings and priorities before a first start or other access-changing operation. If the setup cannot prove that the hub’s eligible source networks reach the configured allow, stop for the human before changing reachability. Do not silently override the human’s drop policy. Add the source-bound drop case to AC-15 and the live-check selftest.

#### F-017 — An allowed UDP port is not an allowed UDP service

With UFW initially inactive and its normal incoming deny policy, consider a unicast DNS listener bound to `<member IPv4>:5353`. The Listener check expressly exempts UDP 5353 under UFW, so it enables the firewall. The stock before rule accepts that port only for the multicast destination `224.0.0.251`; a new unicast query to the member is still denied. The working service is cut off despite passing the guard.

**Attempted refutation:** the new Netid/IPv6 parsing handles the stated socket forms, and multicast discovery on this port normally works. The counterexample uses new unicast traffic, not multicast or an established flow. It is the exception’s packet predicate that is wrong. Firewalld’s UDP 546 exception also assumes the `public` zone’s DHCPv6 service even though the plan intentionally preserves and uses other zones; `drop` has no such service.

**Sources:** [UFW’s actual before rules](https://git.launchpad.net/ufw/plain/conf/before.rules) (fetched directly for this review: lines 46, 68 and 72 constrain DHCP/multicast traffic), [firewalld DHCPv6 service conditions](https://raw.githubusercontent.com/firewalld/firewalld/main/config/services/dhcpv6-client.xml), [the public zone](https://raw.githubusercontent.com/firewalld/firewalld/main/config/zones/public.xml). No firewall was enabled or queried locally or remotely.

**Required correction (PR-4; A-11):** allow an exception only when the prospective firewall preserves the relevant listener traffic, including address family, destination and actual zone/service. Otherwise stop before enable. A port-only list cannot prove this. Add unicast UDP 5353 and a non-public zone without `dhcpv6-client` as negative cases. Existing exceptions must not be inferred solely from stock `public.xml`.

#### F-018 — The broader-rule report drops non-Anywhere sources

Let the member network be `192.0.2.0/25` and an existing UFW SSH allow be from `192.0.2.0/24`. This source-specific rule admits hosts outside the member network, but it is not from `Anywhere`, so the named UFW report omits it. The setup adds its narrower rule and preserves the existing rule, leaving A-4’s mandatory wider-rule warning absent.

**Attempted refutation:** preserving the existing rule is correct; deletion is not requested. `from=` protects the hub key separately and does not narrow the firewall or another retained SSH key. AC-24’s separate “only subnet rules” requirement may catch the rule if independently implemented; this review does not claim that its entire live row must pass. The concrete missing deliverable is the setup/status report required by A-4 and task row 6. The UFW manual explicitly supports source addresses and networks, so the omitted case is a supported ordinary rule form. [UFW rule syntax](https://manpages.ubuntu.com/manpages/noble/man8/ufw.8.html).

The same report’s firewalld branch resolves custom services only in `--list-services`, while a rich rule can name a custom service that covers SSH. Conversely, it calls every non-kit SSH rich-rule accept broader, including one confined to a smaller allowed source network. [Rich-rule services and sources](https://firewalld.org/documentation/man-pages/firewalld.richlanguage.html). These are the same source/coverage classification defect, not separate severity counts.

**Required correction (PR-8; A-4):** determine SSH coverage and whether the allowed source set exceeds the member subnet union. Apply that comparison to source-specific UFW rules and rich-rule service references; retain narrow rules without a false broader warning. Add wider-source and narrower-source cases. Keep the report read-only.

#### F-019 — Mode reader and upstream Strict modes disagree on symlinks

A member may keep `.ssh` as a symlink to a directory owned by the account with mode 0700, with an authorized key at mode 0600 and secure physical parents. The planned GNU/BSD `stat` forms omit `-L`, so the check sees the link’s usual 0777 mode and refuses it. The setup’s existing `install -d`/key write does not turn that directory link into a real directory.

**Attempted refutation:** rejecting writable real directories is correct, and a deliberate stricter policy can be offered to the human. This case already satisfies upstream’s rule: `safe_path()` canonicalizes the key path, uses target metadata, and walks physical parents. The declared distro-patch limitation at `implementation-plan.md:226-227` does not describe this difference from upstream itself. [OpenSSH safe_path](https://raw.githubusercontent.com/openssh/openssh-portable/master/misc.c), [BSD stat’s default lstat and -L semantics](https://man.freebsd.org/cgi/man.cgi?query=stat&sektion=1&format=html).

**Recommendation (PR-4, DR-6):** check canonical targets with the necessary parents, or explicitly document and test a no-symlink policy. This finding is Medium because it stops an otherwise working setup without increasing access; it does not independently block execution under the workflow’s High/Critical threshold.

#### F-020 — D-2’s inapplicable branch can leave a Windows installer active

Row 0 permits the human to resolve four independently dirty files and tests only for `install_cli` in `setup-unix.sh`. A clean result can therefore keep the Windows CLI step while discarding its Unix counterpart. The receipt says `install_cli kept: False`. Row 7a’s actual validation then returns 0 with D-2 still pending; row 8a and the red checker select the static no-pipe guard.

**Attempted refutation:** with `kept: True`, the corrected validators reject pending, B, C, untyped A and A2; this was independently reproduced. If both CLI steps are genuinely discarded, an inapplicable D-2 is harmless. The distinct failure is a retained Windows step: today `Install-Cli` downloads to a file and executes it, so it passes the no-pipe guard while having no installed-binary signature check (`setup-windows.ps1:28-44`, `:98-100`). No rule requires the two retention states to agree. A human can produce this state through ordinary partial keep/discard decisions without forging a receipt.

**Required correction (PR-1, PR-8; explicit typed-ruling requirement):** census both setup scripts and retain platform-specific state, or stop on inconsistency. If either retained step runs, row 7a must wait for the human’s typed A and row 8a must verify the affected binary. No other typed ruling may pass. The plan may treat D-2 as inapplicable only after proving that no CLI step remains on either platform. This is a newly introduced applicability bypass, not a request for more spelling variants of the already-correct A predicate.

### Prior Pass Summary — F-001 through F-014

Earlier findings and correction logs above are preserved as historical text. “Fixed” below means the corrected plan removes the cited counterexample; it does not claim that unstarted kit code has already been changed.

| Finding | Round-3 disposition | Corrected plan and code evidence |
|---|---|---|
| F-001 | **Partly fixed** | `implementation-plan.md:174-192`, `:460-489`: fixed trusted tool path, privileged bash and clean child environments remove the original APT hook route. `:1230` introduces an incomplete policy selector check; F-015 identifies the materially different pre-interpreter failure. Current `setup-unix.sh:105-116` is still the old unrestricted grant, as expected before execution. |
| F-002 | **Fixed** | `implementation-plan.md:206-236`, `:611-619`, `:677-685`, AC-16 `:645`, AC-17 `:700`: public-key enablement, file, methods and exact algorithm checks precede password-off on both paths and are repeated after the candidate change. The original valid `PubkeyAuthentication no` state is rejected. Existing code `setup-unix.sh:92-103` and `setup-windows.ps1:86-94` writes keys but has none of this new checking yet. Declared hub-address/Match/from limits remain visible; no new defect is inferred merely from those accepted review boundaries. |
| F-003 | **Fixed** | Drop-in snapshot/restore `implementation-plan.md:193-201`, step 10 `:615-619`, AC-16 `:645`, A-16 `:1210-1214`: old bytes/owner/mode survive candidate refusal, failed reload triggers restore plus another reload, and later CLI failure preserves the already-applied config. The Unix unit is now resolved even if sshd already listens (`:596-598`), repairing the current code’s start-only assignment at `setup-unix.sh:48-50`. |
| F-004 | **Fixed** | Firewalld rules/checks `implementation-plan.md:254-272`, AC-15 `:644`, task row 6 `task.md:50`: each running-state mutation is queried and applied in runtime and permanent stores, and no reload can resurrect the removed stock service. The old argv counterexample is gone; F-016 concerns packet classification, not permanence. |
| F-005 | **Fixed** | `implementation-plan.md:263-268`, `:307-314`, `:607-610`, AC-15 `:644`: the stopped branch uses the offline client and its zone-specific removal before start, and the stub refuses daemon operations until start. Runtime-only NetworkManager zones are resolved afterwards. F-016 is a new source-zone conflict, not a renamed stopped-daemon failure. |
| F-006 | **Fixed** | `implementation-plan.md:526-552`, AC-13 `:567`, AC-23 `:910`, `task.md:49`, `:59`: active-store rule/filter enumeration, port ranges/lists, service filters and profile state are explicit; marker extraction and encoded SSH delivery connect the same report to the hub. This replaces current `setup-windows.ps1:72-83`’s named-rule-only behavior. The original second broad rule is now reported. |
| F-007 | **Fixed** | `implementation-plan.md:749-762`, AC-19 `:790`: exit 0, GOODSIG, pinned VALIDSIG and the negative status policy jointly gate disk writes; revoked/expired/unknown second signatures are negative cases. Current `write-installer-usb.ps1:29-44` still has only the loose hash check, which the scheduled work replaces. |
| F-008 | **Fixed** | Record retire `implementation-plan.md:237-245`, AC-27 `:646`, `:701`, step 2 `:590`, Windows order `:677-680`: same-name and same-host-key drive records are retired before changes; no new record follows failure. `fleet_usb.py:73-74`, `:176-177` confirms that preserving the folder is safe once only `.old` remains. Existing hub state is not confused with a fresh successful import. |
| F-009 | **Fixed** | Git root rule `implementation-plan.md:297-306`, AC-28 `:415`, image fallback `:749-750`, AC-19 `:790`: both Python and PowerShell implementations find the root across the three stated layouts, reject WSL and share synthetic layout cases. No `parents[1]` recipe remains authoritative. |
| F-010 | **Fixed** | `implementation-plan.md:886-913`, `task.md:43`, `:58`, `:65`, `:83`: baseline-HEAD diff, untracked files, plan and closeout text are included; known machine/member terms and the declared allow rules are covered by AC-29 selftests. The original excluded-file-class hole is removed. No additional blocker is manufactured from generic scanner-evasion variants. |
| F-011 | **Fixed** | `implementation-plan.md:880-885`, `:914`, `:1355-1361`; `task.md:65`, `:69`, `:71`: relevant changed/untracked file bytes enter the state identity and are recomputed before `durable_evidence.py` compares `tested_state` (`core/tools/durable_evidence.py:131-136`). Changing bytes in an already-modified script now changes the specified identity. |
| F-012 | **Fixed** | `task.md:81` supplies both maintainer paths to add/render/render-check and requires the issue ID in both outputs. This directly corrects the different defaults in `core/tools/issue_triage/model.py:23-26`; no issue store was changed by the review. |
| F-013 | **Partly fixed** | `task.md:35`, `:47-48`, `:53-55`, `:104`; `implementation-plan.md:941-943`: silence no longer selects A, dependencies exist, and all tested non-A rulings fail. F-020 remains: the newly added inapplicable branch relies on a Unix-only retention probe and can bypass a still-applicable Windows decision. D-1’s gate itself is fixed. |
| F-014 | **Fixed** | The round-2 correction log names the raw census and its per-hit map. Independent parsing reproduced all hits, dispositions, zero searches, full line text, hashes and sampled current searches; see the PR-6 evidence below. The procedural gate passes and did not prevent this substantive round. |

### PR-6 census evidence

The independent script is `scratch script C:/Temp/zorivest/usb-kit-plan/review-r3/census_audit.py`. Its output is `audit result C:/Temp/zorivest/usb-kit-plan/review-r3/census-audit.json`. It parsed the receipt and map instead of reading the 1.3 MB receipt end to end. The correction log’s external map is the per-hit disposition log requested for this round.

- **562 searches; 1,460 raw hits; 1,460 mapped hits; 1,402 updated; 58 confirmed-consistent; 99 zero-hit searches.** Counter-based equality verifies per-search/per-target/per-file:line membership, including multiplicities. Every disposition is one of the permitted values, and no UNRESOLVED entry remains.
- All 1,460 payloads equal the entire referenced file line, and every search count/exit agrees. Independently recomputed substring sweeps over final, round-1 and round-0 texts agree with every receipt result. Round-0 provenance remains the declared reconstructed snapshot; this review makes no stronger provenance claim.
- Eighteen fresh `rtk proxy rg --no-config -F -n --no-heading --with-filename --color never -e <literal> -- implementation-plan.md task.md` searches, stratified across old/new/variant and hit/no-hit sets, reproduce the current receipt. Samples include `--remove-service`, `VALIDSIG`, `Physical`, `ssh-ed25519`, `reload`, `MSYSTEM`, `Custom SSH`, `docker*`, `wg0` and the zero-hit default-decision wording.
- Current SHA-256: `implementation-plan.md` = `c31633e29f10e06ef41f4bdaba908c4f727306c89aafe3c9ea3c3b179825c494`; `task.md` = `39a9bf49435f3adb8ddeae419af8b3ec4142577e688f7f4953e45f8443f96e49`. Both match the correction log and receipt headers. The round-1 snapshot hashes also match the earlier correction section through the same full-content audit.

### Coverage census

Both current plan files, both correction sections, all old findings, current kit source and its four dirty diffs were read. AC-1 through AC-30, all 43 task rows, all 22 Named definitions, A-1 through A-18, both briefs, all 12 stop conditions and every exclusion were assessed. The advisory N1–N13 labels supplied scope pointers, not authority.

| Surface | Review result |
|---|---|
| WP-U1; AC-1/2/3 | Both constants and the named expected-set change match `fleet.py`’s manifest/hello/capability call chain. Hub-first updating and old-hello refusal remain coherent. No unrequested source-repo edit is scheduled. |
| WP-U2; AC-4/5/6/7/12/28 | Load guards, explicit path seams, PowerShell library parameter sets, 5.1 compatibility, LF rules, bash 3.2 constraints and guard/characterization exceptions are coherent. The root-based Git locator fixes F-009. |
| WP-U3; AC-8/9/10/11/26 | Fixed argv/package grammar, trusted child path/environment, physical helper-parent walk, sudoers validation and exhaustive admin outcomes were checked. Parent ownership/writability checks now cover replacement by an ancestor writer. F-015 remains at interpreter startup; stock parser fixtures cannot prove the omitted selector semantics. |
| WP-U4; AC-13 | Physical-adapter preflight, Public refusal, unchanged categories, effective-store filters, profile state and report transport are explicit and consistent. Port/protocol/service/range cases are accounted for. No additional demonstrated Windows report defect was found. |
| WP-U5; AC-14 Unix/15/16/27 Unix | Record retirement and the original rollback/permanence/stopped-daemon fixes are real. N1/N6/N13 introduce the additional cases in F-016 through F-019. The key check’s original disabled-key/method/file/algorithm cases are fixed. |
| WP-U5w; AC-14 Windows/17/27 Windows | Both SSH process names and WinRM are covered, and snapshot/restart handling is explicit. The effective key-check and marked-block order match the intended password-off behavior. The old record is retired before system changes. |
| WP-U5b; AC-18 | The import call chain and exact `publickey` method-list oracle remain explicit; unknown/refused/timed-out output fails. The declared source/account limits remain visible. |
| WP-U6; AC-19/20 | Image fingerprint/status/hash checks precede disk mutation. Probe-1/Probe-2 are execution work and were not run. F-020 affects CLI applicability; D-2 still honestly discloses that installer code runs before the binary check. |
| WP-U7; AC-21 | Manifest relocation, refresh smoke step, bootstrap port clarification, both README behaviors/Undo steps and helper verbs match the named source files. The setup-member installer issue remains separately tracked by H2-3b. |
| WP-U8; AC-22/23/24/25/29/30 | Gate adapters, coverage inventory, live-member selection, red receipts, privacy scope and content-based freshness were traced. Live tests are not claimed. F-016/F-018 affect Linux firewall evidence; F-020 affects D-2’s applicability. |

| Named definitions | Disposition |
|---|---|
| Kit; Drive folder | Match the current directories and prepare/import contracts. |
| Helper; Sudoers file | Physical parent walk fixes the stated replacement issue; trusted child environment is explicit. F-015 identifies the remaining sudo-selector/startup boundary. |
| Mode reader | GNU/BSD format choice is correct for ordinary files. F-019 concerns symlink dereferencing, a distinct new compatibility failure. |
| Drop-in; Marked block; Password-off check | Prior bytes survive rejected candidates, restore/reload sequencing is now explicit, and late failure keeps the applied state. The macOS no-reload branch is read together with WP-U5 step 11’s explicit keep rule. |
| Key-auth check | Original F-002 counterexamples are rejected before password-off. Exact methods/algorithm/file handling and account filters were assessed against sshd docs. F-019 qualifies the stated upstream Strict modes equivalence. Declared Match/from limitations are not reopened. |
| Record retire | Same-name/key retirement, preservation of other records and clone/rekey limitations are explicit; `.old` is outside import’s glob. |
| Listener check | F-017: the new parser’s socket handling does not establish the new port exceptions’ firewall semantics. |
| Firewalld rules; Firewalld checks | Original offline/permanence/runtime-zone issues are fixed; F-016 adds source classification. |
| Broad-rule report | Windows reachability to the hub is specified. F-018 identifies the Unix source/coverage omissions. |
| Member subnets | IPv4 network calculation, interface exclusions, overlay retention and record/from/firewall consistency are explicit; no unsourced IPv6 expansion is demanded. |
| Load guard; Git bash; Stub folder | Source/library seams, root-based locator and empty-environment stub logging are coherent. Missing live evidence is not disguised by synthetic stock samples. |
| Admin check; Outcomes; Probe; Console guard | Exhaustive outcomes/unknown refusal, named import/probe caller and the disclosed bounded parent walk were traced. No new claim of invulnerable process ancestry is introduced. |

| Task rows (all 43) | Review result |
|---|---|
| PC; 0 | Manual commit/dirty-file ownership boundaries remain explicit. PC’s no-commit branch is corrected. F-020 concerns row 0’s Unix-only retention observation; no dirty file was changed by this review. |
| 1 | Three absent checker/runner paths are scheduled before use, with peer sources. Baseline, selftests, red new modes and content identity are explicit. A red baseline stops for the human. |
| 2; 2a | Constants/expected set and human hub/member update form a coherent sequence. Row 2a remains independently required at H1-1. |
| 3 | Test seams, new test files, Git locator and deliberate green-first guards align with AC-4/5/6/7/12/28. |
| 3a; 4 | D-1 waits for typed A and row 4 depends on it. F-015 affects the chosen-A implementation design, not authorization. |
| 5 | Active-store report and network preflight are included; marker transport is scheduled and selftested. |
| 6; 6a | Ordered Unix/Windows hardening and record retirement align with their ACs. New Linux cases are F-016 through F-019. |
| 7 | Probe order, method-list failure and --no-test skip are explicit. |
| 7a; 8; 8a | The A-vs-other ruling predicate is corrected, image verification is fully gated, and absent Probe-1 verification stops for the human. F-020 concerns an incorrectly inapplicable D-2/CLI branch. |
| 9; 10; 11 | All five docs, regression/targeted suites, peer Pester runner and package/privacy checks are inventoried. |
| 12; 13; 14; 15 | Human-only machine actions, fresh prepare/import, all drive members online, real parser receipts and explicit missing-macOS follow-up are preserved. BUILD_PLAN absence is still an evidenced no-op. |
| H1-1; H1-2 | Required human rows precede closeout; relevant script changes repeat live checks. Fresh full runs record the content identity. |
| H1-3; H1-4; H1-5 | No-MEU/no-API bases and template/exemplar reads are coherent. |
| H1-6; H1-6a; H1-6b | Handoff, AC coverage and content-based full-evidence freshness match the actual validator interfaces. |
| H1-7; H1-7a; H1-7b | Independent execution review, target-bound approval and ledger matching remain explicit. No dispatch or ledger mutation was run here. |
| H2-1; H2-2; H2-3 | Reflection/template/schema and metrics destinations exist; sequencing follows approved execution review. |
| H2-3a; H2-3b; H2-3c | Direct-request grouping/main-tree no-ops remain explicit; issue add/render/check consistently target the maintainer pair. |
| H2-4; H2-5; COMMIT; H2-6 | Final privacy scan, commit draft/identity check, human-only commit and finalization are preserved. No commit or push is authorized by this review. |

### Decision briefs and declared limits

**D-1 remains the human’s.** Its alternatives, fixed verbs, repository-package root-script residual in User Review Required, Windows full-administrator residual and policy/path limits are visible. The brief’s clean-environment assurance must be corrected with F-015 before it is safe to act on. This review chooses no option and does not treat `source_tag` as a ruling.

**D-2 remains the human’s.** Its installer-before-verification residual is correct and explicit; Probe-1 must still establish a real vendor check, and lack of one stops for the human. F-020 must be fixed so that “not applicable” cannot conceal a retained installer. Typed B or any other non-A ruling returns that work to planning. The review does not select the fallback for Codex or authorize either installer route.

The declared Windows administrator scope, package install scripts, macOS firewall exclusion, hub-source/from limits, bounded parent walk, runtime zone movement after setup and missing macOS hardware remain declared limits. They are not reclassified as new defects here. No plan-author forgery threat or missing commit trailer was raised.

### Executed verification and limits

All local launch commands used `rtk proxy` for exact output. Scratch scripts and outputs are under `review scratch C:/Temp/zorivest/usb-kit-plan/review-r3/` only.

| Procedure / command | Exit | Decisive observation |
|---|---|---|
| `rtk proxy python -X utf8 <review scratch>/census_audit.py` | 0 | PR-6 counts, all full-text checks and the 18 live rg samples agree. |
| `rtk proxy python -X utf8 core/tools/lint_task_contract.py --task docs/execution/plans/2026-11-07-usb-kit-hardening/task.md` | 0 | 43 rows; 10 columns; 41 contracts checked; 2 view_file exemptions; dependencies acyclic. |
| `rtk proxy powershell -NoProfile -File <review scratch>/parse.ps1` | 0 | 44 task command snippets and 2 current kit PowerShell files parsed; 0 errors. This is parsing only, not script execution. |
| Existing pure test: `python -X utf8 -m pytest scripts/tests/test_fleet_agent.py::test_ac32_forbidden_commands_are_unchanged -q -p no:cacheprovider --basetemp <review scratch>/pytest` (launched through `rtk proxy`, bytecode disabled) | 0 | **1 passed in 0.52s.** No wider suite or Pester rerun is represented as passing this round. |
| `rtk proxy python -X utf8 <review scratch>/counterexamples.py` | 0 | Actual rows 3a/7a: pending/B/C/untyped A/A2 exit 1; typed A exits 0. Row 7a with the discarded flag and pending D-2 exits 0. Other results are pure contract models, not live parser/firewall/exploit runs. |
| Read-only artifact/status/hash audit | 0 | All 43 rows unchecked; 14 existing validator/test/template references exist; the three absent plan-local executables and new helper are explicitly scheduled. No correlated implementation handoff exists. Both corrected-input hashes match. |
| Unfiltered repeated-literal sweep over both plan files | 0 | 37 full matching lines preserved; named canonical policies govern the restatements. |

The public documentation/source reads were limited to the review’s cited primary sources. A direct public UFW source fetch succeeded where the web viewer could not read the page. No setup/installer, fleet hub/member/run, prepare/import, SSH connection, sudo, visudo, credential read, remote member action or Git write was performed. The separately owned dirty kit files were read only. No new plan AC or not-yet-written checker was executed.

```json
{
  "schema_version": "evidence.v1",
  "id": "R3-CENSUS",
  "phase": "static",
  "command": "rtk proxy python -X utf8 C:/Temp/zorivest/usb-kit-plan/review-r3/census_audit.py",
  "exit_code": 0,
  "result": "pass",
  "observed": "562 searches; 1460 full-text receipt hits equal 1460 disposition rows; 1402 updated; 58 confirmed-consistent; 99 zero-hit searches. Both current input hashes match. All independent substring sweeps and 18 live rg samples match."
}
```

```json
{
  "schema_version": "evidence.v1",
  "id": "R3-COVERAGE",
  "phase": "manual",
  "procedure": "Read the two current plan files, both correction logs and prior findings; compare current kit source, dirty diffs, named production call chains, peer gates and primary documentation. Trace every AC, all 43 task rows, 22 Named definitions, A-1 through A-18, D-1/D-2, stop conditions and exclusions. Attempt the refutations stated under each finding. Distinguish source-backed contract models from executed checks and live observations.",
  "observer": "Codex",
  "command": null,
  "exit_code": null,
  "result": "fail",
  "observed": "PR-6 passes. Six new findings survive refutation: five High and one Medium. Original APT child-environment and automatic-default defects are partly corrected with materially different new failures recorded as F-015 and F-020. The other prior findings are fixed. No live success is claimed."
}
```

### Checklist Results

Observer for the manual entries is Codex, using the R3-COVERAGE procedure above; manual exit is null. Executed results and exact commands are preserved in the preceding table and R3-CENSUS block.

| Check | Result | Evidence |
|---|---|---|
| PR-1 | fail | All 43 rows and all work packages were traced; F-020 makes the shared kept/discarded branch disagree with a retained Windows step. |
| PR-2 | pass | All 43 rows are unchecked; the helper, three plan-local executables, new USB tests and correlated implementation handoff remain absent. The four dirty kit files are the separately owned work. |
| PR-3 | pass | lint_task_contract exited 0: 43 rows, 10 columns, 41 command contracts checked, 2 view_file exemptions; dependencies resolve and are acyclic. |
| PR-4 | fail | F-015 through F-017 demonstrate unsafe policy or first-enable behavior; F-019 demonstrates a working symlink layout that the new check refuses. All 44 extracted command snippets and both kit PowerShell files parse under Windows PowerShell 5.1. |
| PR-5 | pass | All AC-1 through AC-30 carry an allowed source basis. Existing command dependencies were checked; absent executables are explicitly scheduled before use. Pending Human-approved tags are the declared schema exception, not an approval. |
| PR-6 | pass | Independent parser: 562 searches, 1460 full-text hits, 1460 mapped hits, 1402 updated, 58 confirmed-consistent, 99 zero-hit searches. Both input hashes match; all substring re-sweeps and 18 live rg sample searches agree. |
| PR-7 | pass | All exclusions were read against their stated kit scope, decisions and repository state; the setup-member exclusion now has the explicit known-issue follow-up. No unscheduled deferred MEU is used. |
| PR-8 | fail | The new command-selector parser and platform-retention selector have concrete accepting unsafe states (F-015, F-020). The Unix report misses a required broader-rule producer case (F-018). F-016 traces the interface-only queries to a different packet-classification zone. |
| PR-9 | pass | The repeated-literal sweep was preserved untruncated. The helper modes, console bound, password-off sequences, Windows profile policy and outcome set have named canonical definitions; the old duplicate-policy notes are resolved. |
| DR-1 | n/a | No implementation completion claim is under review; this is an unstarted plan. |
| DR-2 | pass | The remaining retired-tool occurrences in the scanned production/test surfaces are the two fleet constants and named expected-set edit that WP-U1 schedules. |
| DR-3 | pass | WP-U7 inventories the manifest move, refresh checklist, bootstrap port clarification and both README updates; the new helper is included in prepare. |
| DR-4 | fail | The original negative cases are now planned. The newly added cases still omit the counterexamples in F-015 through F-020. |
| DR-5 | pass | Independent census audit, actual decision-predicate cases, AST parsing, task lint and one existing pure fleet test have decisive results preserved below. Security counterexamples are source-backed contract models, not claimed live reproductions. |
| DR-6 | fail | The restricted Unix report disagrees with its any-broader-rule contract (F-018); the stated upstream Strict modes rule disagrees with the Mode reader semantics (F-019). |
| DR-7 | pass | Current input hashes match the round-2 correction log. The corrected state identity includes relevant file bytes; the original already-modified-file collision is removed. |
| DR-8 | fail | D-2 accurately discloses installer execution before verification, but F-020 can bypass that decision and verification. D-1’s environment boundary is not yet secured against F-015. Neither decision has been made for the human. |

### Out-of-Contract Observations

- `core/.agent/docs/human-decision-protocol.md:238-245` lacks a pending source-tag value. The declared D-1/D-2 `Human-approved`/pending combination is not a plan defect and is not counted as a finding; applicable rows must still read a genuine typed ruling.

### Verdict and next gate

`changes_required`. **F-015, F-016, F-017, F-018 and F-020 must be corrected before execution starts.** F-019 is Medium and does not independently block. PR-6 passes; this verdict rests on delivery-level failures, not a census procedure failure or a clerical requirement.

This is **round 3 of 3**. The cap is exhausted: preserve these findings and stop for the human’s continuation decision. Do not autonomously start `/plan-corrections`, launch a fourth review, implement kit changes, or select D-1/D-2. If the human authorizes corrections, `/plan-corrections` is the correction route; there is no implied approval or new round allowance. Only this rolling review was changed in the repository.

### Structured verdict — Round 3

```json
{
  "schema_version": "review-verdict.v1",
  "date": "2026-11-07",
  "review_mode": "plan",
  "target_plan": "docs/execution/plans/2026-11-07-usb-kit-hardening",
  "agent": "Codex",
  "requested_verbosity": "detailed",
  "verdict": "changes_required",
  "summary": "Round 3 of 3: PR-6 passes. Five High findings (F-015, F-016, F-017, F-018, F-020) require correction before execution; F-019 is Medium and nonblocking. F-001 and F-013 are partly fixed; the other prior findings are fixed. D-1 and D-2 remain the human’s. The review cap is exhausted; no correction or execution was started.",
  "findings": [
    {
      "id": "F-015",
      "severity": "High",
      "confidence": "High",
      "finding": "A-18 ignores command-specific selectors such as /opt/fleet-admin/* that sudo matches to the helper. A matching setenv default permits command-line LD_PRELOAD before bash -p or env -i executes, allowing root code outside the declared repository-package limit (PR-4, PR-8).",
      "file_line": "docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:1230; :188-192; :1269-1279",
      "recommendation": "Use sudo-native enforcement of the effective environment boundary and reject command-specific matches that cannot be proved unrelated. Cover wildcard/directory selectors and interpreter startup; do not rely on child env -i to protect the interpreter.",
      "status": "open"
    },
    {
      "id": "F-016",
      "severity": "High",
      "confidence": "High",
      "finding": "The firewalld target set includes interface zones only. A source-bound drop zone can classify the hub packet first, while every interface-zone query passes; starting the firewall then blocks the intended SSH connection (PR-4; Goal finding 3 and A-12).",
      "file_line": "docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:254-272; :276-279; :607-619",
      "recommendation": "Check source bindings and zone priorities before the first start or access-changing operation. Stop for the human on conflicting classification rather than silently changing an existing restrictive policy. Add a source-bound drop-zone negative case.",
      "status": "open"
    },
    {
      "id": "F-017",
      "severity": "High",
      "confidence": "High",
      "finding": "The Listener check exempts UDP ports without their destination, service and zone conditions. A non-loopback unicast service on UDP 5353 passes the ufw exception although the stock allowance is multicast-only; enabling default-deny ufw cuts that working service off (PR-4; A-11).",
      "file_line": "docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:246-253; :603-604; :644; :1160-1164",
      "recommendation": "Permit an exception only when the prospective firewall actually preserves the listener traffic. Otherwise stop before enabling. Test unicast UDP 5353 and a firewalld zone without the assumed DHCPv6 service.",
      "status": "open"
    },
    {
      "id": "F-018",
      "severity": "High",
      "confidence": "High",
      "finding": "The Unix Broad-rule report undercounts wider source allowances: its ufw branch accepts only From Anywhere, so an existing TCP 22 allow from a supernet of the member subnet is not reported. This omits A-4’s required security warning even though the rule still opens SSH beyond the intended networks (PR-8).",
      "file_line": "docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:273-280; :601-604; :634; :911; :1090-1094",
      "recommendation": "Compare each SSH-covering allow source with the allowed subnet union, including address/CIDR sources. Also resolve custom services used in rich rules and avoid classifying a narrower non-kit rule as broader. Keep reporting read-only.",
      "status": "open"
    },
    {
      "id": "F-019",
      "severity": "Medium",
      "confidence": "High",
      "finding": "The Mode reader uses stat without dereferencing symlinks, but the Strict modes check claims upstream safe_path behavior. A secure .ssh symlink is read as mode 0777 and refused although OpenSSH checks its canonical target and accepts it (PR-4, DR-6).",
      "file_line": "docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:185-187; :224-227; :645; .agent/fleet/usb/setup-unix.sh:94-103",
      "recommendation": "Define the Key-auth check on canonical paths and target metadata, with the necessary parent checks, or explicitly disclose and test a deliberate no-symlink restriction. Do not describe lstat semantics as upstream safe_path.",
      "status": "open"
    },
    {
      "id": "F-020",
      "severity": "High",
      "confidence": "High",
      "finding": "Row 0 determines whether the CLI step was kept by reading only setup-unix.sh. If the human keeps the Windows step and discards the Unix step, row 7a passes a pending D-2 as not applicable and row 8a selects only the no-pipe guard. The Windows download-to-file installer remains unverified (PR-1, PR-8; explicit typed-ruling requirement).",
      "file_line": "docs/execution/plans/2026-11-07-usb-kit-hardening/task.md:42; :53; :55; docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:767-776; :869-870; .agent/fleet/usb/setup-windows.ps1:28-44; :98-100",
      "recommendation": "Determine retention for both platform scripts. A retained step on either platform must require the human’s typed A and verification for that platform; inconsistent retention must stop for planning or be represented explicitly.",
      "status": "open"
    }
  ],
  "checklist_results": [
    {
      "check": "PR-1",
      "result": "fail",
      "evidence": "All 43 rows and all work packages were traced; F-020 makes the shared kept/discarded branch disagree with a retained Windows step."
    },
    {
      "check": "PR-2",
      "result": "pass",
      "evidence": "All 43 rows are unchecked; the helper, three plan-local executables, new USB tests and correlated implementation handoff remain absent. The four dirty kit files are the separately owned work."
    },
    {
      "check": "PR-3",
      "result": "pass",
      "evidence": "lint_task_contract exited 0: 43 rows, 10 columns, 41 command contracts checked, 2 view_file exemptions; dependencies resolve and are acyclic."
    },
    {
      "check": "PR-4",
      "result": "fail",
      "evidence": "F-015 through F-017 demonstrate unsafe policy or first-enable behavior; F-019 demonstrates a working symlink layout that the new check refuses. All 44 extracted command snippets and both kit PowerShell files parse under Windows PowerShell 5.1."
    },
    {
      "check": "PR-5",
      "result": "pass",
      "evidence": "All AC-1 through AC-30 carry an allowed source basis. Existing command dependencies were checked; absent executables are explicitly scheduled before use. Pending Human-approved tags are the declared schema exception, not an approval."
    },
    {
      "check": "PR-6",
      "result": "pass",
      "evidence": "Independent parser: 562 searches, 1460 full-text hits, 1460 mapped hits, 1402 updated, 58 confirmed-consistent, 99 zero-hit searches. Both input hashes match; all substring re-sweeps and 18 live rg sample searches agree."
    },
    {
      "check": "PR-7",
      "result": "pass",
      "evidence": "All exclusions were read against their stated kit scope, decisions and repository state; the setup-member exclusion now has the explicit known-issue follow-up. No unscheduled deferred MEU is used."
    },
    {
      "check": "PR-8",
      "result": "fail",
      "evidence": "The new command-selector parser and platform-retention selector have concrete accepting unsafe states (F-015, F-020). The Unix report misses a required broader-rule producer case (F-018). F-016 traces the interface-only queries to a different packet-classification zone."
    },
    {
      "check": "PR-9",
      "result": "pass",
      "evidence": "The repeated-literal sweep was preserved untruncated. The helper modes, console bound, password-off sequences, Windows profile policy and outcome set have named canonical definitions; the old duplicate-policy notes are resolved."
    },
    {
      "check": "DR-1",
      "result": "n/a",
      "evidence": "No implementation completion claim is under review; this is an unstarted plan."
    },
    {
      "check": "DR-2",
      "result": "pass",
      "evidence": "The remaining retired-tool occurrences in the scanned production/test surfaces are the two fleet constants and named expected-set edit that WP-U1 schedules."
    },
    {
      "check": "DR-3",
      "result": "pass",
      "evidence": "WP-U7 inventories the manifest move, refresh checklist, bootstrap port clarification and both README updates; the new helper is included in prepare."
    },
    {
      "check": "DR-4",
      "result": "fail",
      "evidence": "The original negative cases are now planned. The newly added cases still omit the counterexamples in F-015 through F-020."
    },
    {
      "check": "DR-5",
      "result": "pass",
      "evidence": "Independent census audit, actual decision-predicate cases, AST parsing, task lint and one existing pure fleet test have decisive results preserved below. Security counterexamples are source-backed contract models, not claimed live reproductions."
    },
    {
      "check": "DR-6",
      "result": "fail",
      "evidence": "The restricted Unix report disagrees with its any-broader-rule contract (F-018); the stated upstream Strict modes rule disagrees with the Mode reader semantics (F-019)."
    },
    {
      "check": "DR-7",
      "result": "pass",
      "evidence": "Current input hashes match the round-2 correction log. The corrected state identity includes relevant file bytes; the original already-modified-file collision is removed."
    },
    {
      "check": "DR-8",
      "result": "fail",
      "evidence": "D-2 accurately discloses installer execution before verification, but F-020 can bypass that decision and verification. D-1’s environment boundary is not yet secured against F-015. Neither decision has been made for the human."
    }
  ]
}
```

🕐 Completed: 2026-11-07 14:51 (EST)

## Corrections Applied — 2026-11-08, round 3

Applied by the plan's author through `/plan-corrections`. This section is not an approval. All earlier text in this file is unchanged, except the frontmatter `verdict:` value, which `plan-corrections.md:245-247` sets to `corrections_applied`. Only an independent reviewer can set `approved`.

This pass covers F-015 to F-020 of round 3, the human's two rulings, the extra review rounds and a scope addition. Each finding was checked against the cited code and the primary sources first. All six held, and none is dismissed. The rule for this pass: where the setup cannot prove that a change keeps the hub's access and the existing traffic, or that a sudo policy is safe, it stops before the change and names what it found. Checks were narrowed or removed, not extended with more cases. Line numbers are for the final files: `plan` is `implementation-plan.md` and `task` is `task.md`.

Human direction in this pass:

- **Review rounds.** The human typed "Add 3 more rounds" on 2026-11-08. The plan loop is now 6 rounds: 3 from `core/.agent/review-limits.json` and 3 from the human (plan:89-90). The execution loop stays 6 rounds. The plan loop's token budget stays 10,500,000, because the human did not change it; 6 rounds share it now. `task.md` states only the execution cap (task:33), so it needed no change. The round-3 heading above says "Round 3 of 3" and stays as written.
- **D-1 and D-2 ruled A.** The coordinator relayed the human's words "recoomendations for D-1 D-2 accepted" (2026-11-08). The author did not see the human's message, and each record names the relay (plan:102-105, :1081, :1091, :1291, :1334-1335; task:35). Rows 3a and 7a still check the typed line before rows 4 and 8a (task:47, :53). The round-3 changes make option A stricter, not different: D-1's `chosen` (plan:1081) keeps the option text that the human accepted, and its reasoning (plan:1085) and brief (plan:1284-1292, :1313-1322) name the `NOSETENV:` tag, `!env_check` and the probe that F-015 added. If the human reads that as a different option, D-1 goes back to the human.

| Item | Disposition | Correction | Where | Evidence |
|---|---|---|---|---|
| F-015 | fixed | The kit no longer proves which `Defaults!` selector matches the helper. The rule line is now `<user> ALL=(root) NOPASSWD: NOSETENV: /opt/fleet-admin/fleet-admin`, and the `Defaults!` line adds `!env_check`, so sudo itself refuses `-E` and any `VAR=value`, `LD_PRELOAD` included, whatever selector form sets `setenv`. A-18 stops on any general line that keeps or sets variables, on any Runas or command-specific line other than the kit's, on any `SETENV:` tag, on an unknown header, and, on the second read, on a last command entry that is not the kit's `NOSETENV:` rule. After the write, the setup runs `LC_ALL=C sudo -n LD_PRELOAD=/nonexistent.so /opt/fleet-admin/fleet-admin no-such-verb` and needs sudo's not-allowed line. A stop on the second read or the probe removes the file. AC-26 adds the wildcard and directory selectors, `(ALL) SETENV: ALL`, `(ALL) ALL`, a last rule without `NOSETENV:`, and a probe that runs the helper. D-1's brief states the boundary. | plan:195-200 (Sudoers file), :454-488 (WP-U3), :507 (AC-26), :655, :973-976 (stop 6), :1266-1275 (A-18), :1284-1301, :1313-1322 (D-1 brief), :1358-1359; task:48 (row 4) | sudo 1.9.15p5 `sudoers.c`: `update_defaults(SETDEF_CMND)` runs before the lookup, and the matched rule's tags apply after it, so `NOSETENV` beats a `setenv` default; `lookup.c` and `env.c`: the `setenv` flag gates `-E` and `VAR=value`. `sudoers.man.in`: the last matching rule wins, `ALL` implies `SETENV`, and a `Defaults!` line matches by path, directory, wildcard or alias. ld.so(8): `LD_PRELOAD` is honored outside secure-execution mode. Limit: the macOS form is written from the sources; row 14 runs the parser and the probe there. |
| F-016 | fixed | Before any firewall change, the setup reads `--zone=<zone> --list-sources` for each zone of `--get-zones`, at runtime and with `--permanent` when firewalld runs, or with `firewall-offline-cmd` when it is stopped, and the target of each target zone. A source in a zone that is not a target zone stops the setup at any priority, with both named; the kit does not model priorities. A target zone whose target is not `default` or `ACCEPT` stops it too, so the kit never puts an allow over the human's `DROP` or `%%REJECT%%` zone. The Firewalld checks run both stops again on the runtime zones. AC-15 adds the source-bound `drop` case in both branches, the two targets, and a source in a target zone that passes. AC-24's selftest adds a source outside the target zones and a `DROP` target. | plan:262-272 (Firewalld rules), :286-287 (Firewalld checks), :653-654, :664 (AC-15), :949 (AC-24), :974, :1368; task:50 (row 6) | firewalld "Zone Priorities" (2023-04): at equal priority a source binding classifies a packet before its interface. `drop.xml`: target `DROP`; `block.xml`: target `%%REJECT%%`. firewall-cmd(1): `--get-zones`, `--list-sources`, `--get-target`. |
| F-017 | fixed | The Listener check now excepts only a `tcp` listener on port 22. Every UDP exception is gone, so a unicast UDP 5353, UDP 68 or UDP 546 socket stops the setup before a firewall that was off is enabled. The kit no longer infers which traffic a firewall keeps. User Review Required states the cost: a desktop's mDNS and DHCP client sockets stop the enable, and the human turns the firewall on after checking them. | plan:256-261 (Listener check), :122-124, :664 (AC-15), :680, :1196-1205 (A-11) | ufw `before.rules`: UDP 5353 is accepted only to 224.0.0.251. firewalld `dhcpv6-client.xml`: UDP 546 only to fe80::/64, and only in a zone that has that service. A port number alone cannot prove what a firewall keeps, so the check stops. |
| F-018 | fixed | The Broad-rule report is now the SSH rule report (`report_ssh_rules`). On Unix it lists, read-only, each rule that may let a packet reach port 22 and that the kit did not make, whatever its source, as `other SSH rule, not changed by the kit: <zone>: <rule>`. It never calls a Unix rule broader, because the kit does not compare source sets. `ufw` `ALLOW` and `LIMIT` rules from any source, rich rules that name a service whose `--info-service` ports cover 22, and a zone target of `ACCEPT` are listed. The live check fails on any listed rule, so the human decides. Windows keeps `Find-BroaderSshRule`, whose subnet test proves each listed rule broader. AC-15 lists a wider `ufw` `/24` rule and a narrower rich `/26` rule, both with the neutral line; AC-24 needs an empty report. | plan:288-298 (SSH rule report), :126, :464, :524, :620, :654, :664 (AC-15), :675, :693, :949 (AC-24), :1126-1131 (A-4); task:50 | ufw(8): a rule can name a source address or network. firewalld.richlanguage(5): a rich rule can name a service and a source. A-4 stays: report, never delete. |
| F-019 | fixed | The reviewer's second option: a no-symlink policy. WP-U5 step 1 stops the setup, with the path named, when the home folder, `.ssh` or `authorized_keys` is a symlink (`test -L`). Strict modes now says "upstream's `safe_path()` rule, minus symlinks". AC-16 adds the three link cases, each stopping at step 1 before any change. Stop 6 names a symlink. | plan:607-608 (step 1), :232-235 (Strict modes), :665 (AC-16), :975; task:50 | FreeBSD stat(1): the default reports the link itself unless `-L` is given. OpenSSH `misc.c` `safe_path()` checks the target. The Mode reader reads a link, and step 8 writes as root, so the setup stops on a link instead of reading through it. |
| F-020 | fixed | Row 0 now records both scripts: `install_cli kept:` for `setup-unix.sh` and `Install-Cli kept:` for `setup-windows.ps1`. Row 7a reads both scripts again and reports `inconsistent` when the receipt lacks a line or disagrees with a script. It passes `not applicable` only when both lines are False, and otherwise only on the typed A. Row 8a verifies the binary on each platform whose script kept the step, with the Pester red receipt `uk-red-u6b-pester.txt`. `--acs-if-cli-kept` reads both lines, and a missing line fails. D-2 applies if either script keeps its step. | task:42 (row 0), :53 (row 7a), :55 (row 8a); plan:97, :639, :798-802, :823 (AC-20), :838-839, :898, :906-908, :1330-1335 (D-2 brief) | Current `setup-windows.ps1:28-44`, `:98-100`: `Install-Cli` downloads to a file and runs it, so the no-pipe guard does not catch it. |

### Scope addition — human, 2026-11-08

The coordinator relayed the human's words "add it" (2026-11-08) for four items. They sit inside the existing rows and packages; no task row was added. The plan grew by 28 lines in this part (1378 to 1406) and `task.md` by 0 lines.

| Item | Change | Where |
|---|---|---|
| `import` pin refusal | Before it pins, `import` prints each record's name and `SHA256:` fingerprint. A record whose name `fleet_members.json` already pins with another `host_key` changes nothing: its entry, its `Host` block in `fleet_config` and its line in `fleet_known_hosts` stay. `import` prints the old and new fingerprints and the Undo steps, counts that record as failed (exit 1), and imports the other records. The Undo steps are the README's hub steps (`usb/README.md:93-94`), then `import` again. This replaces today's re-pin (`fleet_usb.py:195-197`). New AC-31; `AC_COUNT` 31; row 7 runs `--acs 18,31`. | plan:741-752 (WP-U5b), :766 (AC-31), :883, :971-972 (stop 5); task:52 (row 7) |
| Name-clash stop | Before any system change, the setup stops when `members/<name>.json` holds another `host_key`, or when this machine has no host key file yet, and prints the rename-or-delete message. Only a record with this machine's own host key is retired. Both AC-27 halves carry the same cases. | plan:245-255 (Record retire), :609 (step 2), :657, :666 and :723 (AC-27), :975, :1211 (A-12); task:50 (row 6), :51 (row 6a) |
| Fingerprints | Each setup prints this machine's `SHA256:` fingerprint, in the form `ssh-keygen -lf` prints, at the end of a passing run, just before it writes the record; a fingerprint that cannot be read stops the setup with no record. `import` prints each record's fingerprint (above). | plan:641-642 (step 12), :701, :722 (AC-17), :738 (WP-U5w), :1372 |
| README | `usb/README.md` tells the human to compare the fingerprints, to treat an unknown name as tampering, that one drive may serve several members whose names must differ, that every member must be reachable at `import` (which can run again), to compare on every machine, and to keep the drive with you. This is a WP-U7 item and row 9's text; no README is edited by this pass. | plan:857-860 (WP-U7), :867, :876; task:56 (row 9) |
| Limits | A new risk bullet: the drive is not signed, and a first `import` pins what the drive holds (plan:163-164). `--expect` lists and signed records are out of scope (plan:1003). The User Review Required paragraph names the addition (plan:107-109). | plan:107-109, :163-164, :1003 |

The fingerprint step replaces the failing CLI step as the late failure in AC-16, AC-17 and AC-27, because it runs on every setup; the CLI cases stay in AC-20.

**Blast-radius census:** 569 values changed, 58 variants swept, 2254 sites found, 2121 updated, 133 confirmed consistent.

The 627 declared values are 129 old, 440 new and 58 variants. 356 are declared by hand and 271 come from the code spans that a script derived from the diff (`derived-values.txt`). Every round-1 and round-2 value runs again, so an old value cannot come back unseen. Three round-2 values moved to old: `Broad-rule report`, `report_broad_rules` and `pending`. The scope-addition terms are declared values: `re-pin`, `host key changed`, `changed key`, `pin refusal`, `retired`, `name clash`, `rename-or-delete`, `fingerprint`, `SHA256:`, `tampering`, `--expect` and others. The script ran 885 searches. `r1` is the text before this pass, which round 2 corrected, and `r0` is the round 0 text that round 2 rebuilt.

| Class | Target | Searches | Hits | Updated | Confirmed consistent | Zero-hit |
|---|---|---|---|---|---|---|
| old | final | 129 | 60 | 60 | 0 | 103 |
| old | r1 | 129 | 172 | 141 | 31 | 41 |
| old | r0 | 129 | 78 | 78 | 0 | 82 |
| new | final | 440 | 1396 | 1389 | 7 | 1 |
| variant | final | 58 | 548 | 453 | 95 | 2 |
| **Total** | | **885** | **2254** | **2121** | **133** | **229** |

- Disposition is defined as in round 2. For a final hit, `updated` means the line differs from round 0, and the map names the round that changed it. `confirmed-consistent` means the line is the same as in round 0 and was read against the corrected text.
- The 60 old-value hits in the final text each have a reason in the map's last column. Unresolved: 0.
- The zero-hit new value is `host key changed`, the coordinator's term; the plan says `changed key` and `changed host key`. The two zero-hit variants are `default if` and `Default if`.
- The read list holds 343 distinct final lines: 66 changed only in round 3, 72 changed in an earlier round and in round 3, 125 changed only in earlier rounds, and 80 unchanged since round 0. This pass read all 60 old-value final hits, all 138 lines that round 3 changed, the 7 confirmed-consistent new-value hits, and each unchanged line that a round-3 variant hits. The other lines are hit only by round-2 variants, and round 2 read them.

Receipts (`receipts in C:/Temp/zorivest/usb-kit-plan/corrections-r3/`):

- `census-receipt.txt`: every search, its exit code and each matching line in full.
- `disposition-map.txt`: one row per receipt hit, with the zero-hit rows.
- `census-summary.txt`, `derived-values.txt`, `read-list.txt`, `census-verify.txt`, `census-audit-r3.txt` and `census-audit-r3.json`.
- `before/` (the `r1` text), `r0/`, `after-pass1/` and `after-pass2/`.
- `fetched/` to `fetched4/` and `dl-sshkeygen/`: the sudo 1.9.15p5 sources, the firewalld and ufw files, OpenSSH `sshkey.c`, `misc.c` and `ssh-keygen.1`, ld.so(8), and the stock sudoers files of Debian, Fedora and macOS.
- `tools/`: the census, verify and audit scripts and the edit blocks of each pass.

**Verification:** `census_verify.py` passes (`census-verify.txt`: searches 885, receipt hits 2254, map rows 2254, zero-hit 229). `census_audit_r3.py` exits 0: it repeats all 885 substring sweeps over the three texts, runs a live `rg` sample per class and checks both hashes. It is the round-3 reviewer's `census_audit.py` with only the folder, the two hashes and the expected counts changed (`audit diff in 151-audit-diff.txt of the receipts folder`). `lint_task_contract.py` passes with 43 rows (`lint-final.txt`). The privacy scan of both plan files and this file finds 0 hits (`privacy-final.txt`). No AC was executed, because every correction is plan text and the tests do not exist yet.

Deviations from the reviewer's suggested shape:

- F-015: no wider selector parser. `NOSETENV:` and `!env_check` carry the boundary in sudo, and A-18 stops on any line it cannot prove unrelated.
- F-016: any foreign source binding stops the setup; the kit does not compare priorities.
- F-017: no UDP exception at all, instead of a packet-level model.
- F-018: no source-set comparison on Unix; every non-kit SSH rule is listed neutrally.
- F-019: the no-symlink policy, not a canonical-target check.
- Pass 3 narrowed two "before any change" phrases in the Firewalld rules and AC-15 to name the change they precede. Pass 4 restated WP-U3's opening line with D-1 ruled A (plan:456).

Residual risks:

- A `ufw` that is inactive shows no rules, so the SSH rule report sees them only after the enable. The real `ufw` and `firewalld` output forms are confirmed only by row 13.
- The order of `sudo -l` entries, and so the last-entry check, is confirmed only by rows 13 and 14. The real macOS `sudo -l` output is not seen before row 14.
- A desktop with mDNS or DHCP client sockets stops at the firewall enable, by design.
- Row 7a reports `inconsistent` if rows 4 to 6 change the CLI markers that it reads in the scripts.
- A first `import` pins what the drive holds; the fingerprint compare is the only check.
- 6 plan rounds share the unchanged 10,500,000-token budget.

**Open human decisions:** none. D-1 and D-2 are ruled A, as relayed. This pass adds no new human decision.

Corrected input SHA-256 values (`implementation-plan.md` has 1406 lines, 45 more than before this pass; `task.md` has 108 lines and 43 rows):

- `implementation-plan.md`: `144f73d372b9be54288083ed0fb9a38d15b78e2b5c14c81de92935cdaef4c873`
- `task.md`: `1926f915180848868ba825352bd50b541b195cd97cb65953775b8d893b6b6729`

🕐 Completed: 2026-11-08 10:22 (EST)


## Recheck (2026-11-08) — Round 4 of 6

Executing this plan should produce a usable USB setup for Windows, macOS and Linux, close the seven original gaps, and add the four approved safeguards for a drive that visits several members. The corrected plan removes the round-3 counterexamples, but two new failures prevent approval: normal desktop sockets cannot satisfy the live gate, and permanent firewalld targets can conceal the running policy; a sudo fixture also needs a nonblocking correction.

**Verdict:** `changes_required`. **Round:** 4 of 6; rounds 5 and 6 remain under the human's 2026-11-08 extension. **Scope:** plan review only, with the human's reading at the plan-to-execution gate as the terminating trust anchor. No author-forgery theory or new decision on D-1/D-2 is used.

### Findings

In this section, `plan` means `docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md`, and `task` means the adjacent `task.md`. These references are to the unchanged inputs whose hashes appear below.

| ID | Severity | Confidence | Blocking | Kind | Finding and failure | File:line | Recommendation | Status |
|---|---|---|---|---|---|---|---|---|
| F-022 | High | High | yes | behavior | The TCP-22-only check stops an ordinary Ubuntu Desktop first run on Avahi/DHCP sockets. The documented manual-enable workaround can let a rerun finish, but AC-24 unconditionally requires the same real socket text to pass that check after setup. Turning the firewall on does not remove those sockets. The main desktop target cannot complete the required live gate while retaining its normal services. | `plan:122-124`, `:256-261`, `:622-628`, `:891-895`, `:949`, `:1201-1205`; `task:60`; `.agent/fleet/install-usb/README.md:12-18`, `.agent/fleet/usb/README.md:46-51` | Define a usable first-enable/resume path for the desktop target and separate output-format parsing from the first-enable safety decision in AC-24. If manual review/enable is retained, state the resume action and test that an active-firewall rerun and the live gate pass with the same ordinary sockets. Do not restore unsafe port-only UDP exceptions. | open |
| F-023 | High | High | yes | control-defeat | mechanism: permanent-target-substituted-for-runtime-policy. The new target stop and SSH report read `--permanent --get-target`. A zone can still run with target `ACCEPT` while its permanent target is `default`; the no-reload pass preserves that difference. The kit's narrow rich rules and stock-service queries pass, the new target report is empty, and AC-24 can accept a firewall that still admits SSH from outside the subnet. | `plan:266-287`, `:291-294`, `:653-654`, `:949`; `task:50`; upstream firewall-cmd runtime/permanent branches | Read the effective runtime target before a running-state mutation and for the report/live check, separately from the permanent target. Use a runtime-capable observable such as zone `--list-all`/runtime zone settings, or stop on an unprovable difference. Add divergent runtime/permanent ACCEPT and DROP cases without reintroducing reload. | open |
| F-021 | Low | High | no | clerical | AC-26's positive rerun fixture uses the sudoers-file tag order `NOPASSWD: NOSETENV:`, while sudo prints `NOSETENV: NOPASSWD:`. A literal last-entry comparison would reject the kit's valid rule, remove its file and stop setup; the plan does not mandate a literal comparison, so this is a readily inferable fixture correction, not a demonstrated universal stop. | `plan:507`, `:612-614`, `:1271`, `:1315-1319`; `task:48`; upstream `sudoers_format_cmndspec()` and `display_priv_short()` | Use the actual emitted order in the positive fixture and compare command-tag values independently of display order. | open |

F-022 and F-023 must be corrected before execution starts. F-021 is a nonblocking correction note under the workflow's Materiality Gate. The following refutations were attempted before retaining them.

#### F-021 — A correct rule is not printed in its input order

The new security policy removes the wildcard/directory `setenv` counterexample. The formatter emits `(root) NOSETENV: NOPASSWD: /opt/fleet-admin/fleet-admin`; AC-26's positive rerun sample spells the tags in the opposite order.

**Refutation:** the tags have equivalent sudoers semantics and a semantic comparison can already satisfy A-18; no implementation exists that proves a literal comparison will be used. The concrete failure is conditional: copying the fixture's presentation into an exact string test rejects a safe setup at its mandatory second read. The correct source form is readily inferable, so the Materiality Gate makes this Low, not a blocker. Correct the fixture and make that normalization explicit. [sudo formatter](https://raw.githubusercontent.com/sudo-project/sudo/SUDO_1_9_15p5/plugins/sudoers/fmtsudoers.c), [listing caller](https://raw.githubusercontent.com/sudo-project/sudo/SUDO_1_9_15p5/plugins/sudoers/display.c).

The read-only model derives tag emission order from the fetched formatter and compares its emitted entry with A-18. It does not execute sudo, visudo or an implemented kit parser; none of those was run.

#### F-022 — The proposed recovery does not satisfy the live contract

Ubuntu documents that UFW is normally disabled. Its [26.04 desktop metapackage](https://packages.ubuntu.com/resolute/ubuntu-desktop-minimal) recommends `avahi-daemon`. Avahi opens a wildcard UDP socket for mDNS; this is a normal daemon socket rather than a custom network server. DHCP client sockets provide additional ordinary examples. Under the new definition, `udp UNCONN ... 0.0.0.0:5353 ...` stops the first enable and setup exits before key/password/fingerprint/record completion. The same applies before starting a stopped firewalld.

**Refutation:** a fail-closed first stop is permitted and is safer than the removed port exceptions. The human can review services, enable the firewall and rerun. However, `plan:894` routes the real post-setup socket text into the Listener check, and `plan:949` requires that text to pass. The still-running Avahi socket fails again even with a correct active firewall; turning the firewall on is not a repair for that test. The narrower interpretation that the live row checks syntax only would solve this part, but is not the current definition: the same named check both parses and stops, and no syntax-only/live distinction is specified. PR-4 and Goal's required passing Linux import/live result therefore remain undeliverable on the stated desktop target. [Ubuntu firewall defaults](https://documentation.ubuntu.com/security/security-features/network/firewall/), [Avahi socket producer](https://raw.githubusercontent.com/avahi/avahi/master/avahi-core/socket.c), [Avahi UDP service documentation](https://manpages.ubuntu.com/manpages/focal/man5/avahi-daemon.conf.5.html).

The socket cases were evaluated as the written contract, not against a live Ubuntu machine. No UDP number was treated as proof that a firewall preserves its traffic.

#### F-023 — A permanent target cannot establish the current target

Take an active interface zone with runtime target `ACCEPT`, no foreign source binding and no other explicit SSH allow. A prior administrator changed only its permanent target to `default` and has not reloaded. That is an ordinary, supported state. The plan intentionally avoids reload to preserve runtime changes. Its new target query sees `default`; it adds subnet rich rules in both stores and removes the stock SSH service if present. The running target still accepts unmatched traffic. The SSH report reads the permanent target too and therefore misses the broad runtime accept.

**Refutation:** runtime service and rich-rule queries, source enumeration, and the new check after the pass all help with their own observables. None supplies the missing runtime target: repeating the permanent query for the runtime zone's name still reads the wrong store. A runtime DROP/permanent-default difference similarly escapes the promised pre-mutation stop. These are newly introduced target-observable defects; the old source-bound-drop counterexample of F-016 is fixed. PR-8 requires a producer for the effective observable and a negative oracle; A-4 and AC-24 require the remaining SSH reachability to be reported. [firewall-cmd store and target semantics](https://firewalld.org/documentation/man-pages/firewall-cmd.html), [zone target behavior](https://firewalld.org/documentation/man-pages/firewalld.zone.html), [runtime list-all producer](https://raw.githubusercontent.com/firewalld/firewalld/main/src/firewall-cmd.in).

This was a contract/state model and source trace, not a firewall operation. A target mismatch needs no forged record and no hostile plan author.

### Prior Pass Summary — required rechecks

“Fixed” means the corrected plan removes the earlier counterexample; it does not mean the kit has been implemented. New defects introduced by a correction have separate IDs above.

| Finding | Round-4 disposition | Corrected plan and current-code evidence |
|---|---|---|
| F-015 | **Fixed; fixture note F-021** | `plan:195-200`, `:477-483`, `:507`, `:1271`: explicit `NOSETENV`, both cleared lists, rejection of all foreign command/runas defaults, second read and account-context LD_PRELOAD probe remove the wildcard/directory startup route. `sudoers.c` applies defaults before lookup; `lookup.c` applies the matched tag; `env.c` rejects the assignment. Current `setup-unix.sh:105-116` remains the old block, which row 4 schedules for replacement. F-021 is a nonblocking source-fixture note, not a renamed injection route. |
| F-016 | **Fixed; new target-observable defect F-023** | `plan:266-271`, `:286-287`, AC-15 `:664`, AC-24 `:949`: every zone's sources are checked before the change, in both applicable stores/offline branch. A source in non-target `drop` now stops before start. Current `setup-unix.sh:54-63` has no firewalld path yet, consistently with pending row 6. Runtime target selection in the added target control is separately defective. |
| F-017 | **Fixed; new usability defect F-022** | `plan:256-261`, `:664`, `:1201-1205`: no UDP port exception survives, so the earlier unicast-5353/UDP-546 unsafe-enable cases stop. Removing exceptions is a real safety fix. The resulting normal-desktop/live-gate dead end is a different failure. |
| F-018 | **Fixed; new target-observable defect F-023** | `plan:288-298`, `:664`, `:1131`: source-specific UFW rules, rich-rule service references and narrower sources are included with neutral text. No Unix source-set comparison or false claim of “broader” remains. `setup-unix.sh:54-63` still only adds the old UFW rules; the new report is scheduled in `fleet-admin.sh` through rows 4/6. The added target clause uses the wrong store. |
| F-019 | **Fixed** | `plan:232-235`, `:607-608`, AC-16 `:665`, `task:50`: a documented, tested no-symlink policy replaces the inaccurate upstream-equivalence claim. This was an offered round-3 remedy. Ordinary real home/.ssh paths pass; an intentional symlink layout stops before changes. Current `setup-unix.sh:94-103` explains why following an unverified link during the root write was undesirable. |
| F-020 | **Fixed** | `task:42`, `:53`, `:55`; `plan:798-807`, `:906-908`: both scripts are censused and verified on the retained platforms. Twelve evaluations of the actual row-7a Python with in-memory file inputs passed the expected outcomes: four matching platform combinations pass, eight missing/mismatched cases fail, and only both-discarded is inapplicable. Current Windows `Install-Cli` at `setup-windows.ps1:28-44`, `:99-100` remains active and is now covered. |
| F-001 | **Fixed** | `plan:181-200`, `:477-483`, AC-26 `:507`: fixed privileged startup and tool environments remove the original APT_CONFIG hook path and F-015's follow-on interpreter route. A-18 explicitly says the probe runs **as the account**, not as the root setup process (`:1271`). The accepted repository-package install-script residual remains disclosed at `:143-147`. F-021 does not reinstate that exploit. |
| F-013 | **Fixed** | `plan:102-105`, `:1081`, `:1091`, `:1284-1292`, `:1330-1335`; `task:35`, `:47-48`, `:53-55`, `:104`: the current user's explicit ruling supplies the human trust anchor; silence is not a decision. Rows 3a/7a still require typed A, dependencies precede code, and F-020's platform bypass is gone. No transcript-forgery or missing provenance finding is raised. |

F-002 through F-012 and F-014 retain their round-3 fixed dispositions. Their corrected key-auth/rollback, offline/permanence, Windows reporting, signature, record-retirement, locator, privacy, byte-bound evidence, issue-store and census controls were cross-checked in the full coverage pass; no older ID is reopened.

### PR-6 — independent census gate

**Pass, before substantive review.** The review used a newly written parser, not the planner's `census_audit_r3.py`. The log's link to the per-hit map was followed; receipt entries and dispositions were joined by search ID, class, target and `file:line`, including multiplicity. Every receipt line was compared with its complete source line, every declared search was independently repeated as a substring sweep over its stated final/r1/r0 inputs, and a stratified sample was repeated using live, literal, unfiltered `rg` against the current plan files.

| Check | Reproduced result |
|---|---|
| Declared values / searches | 627 distinct declarations: 129 old, 440 new, 58 variants; 885 searches |
| Hits / dispositions | 2,254 hits = 2,254 disposition rows; 2,121 updated + 133 confirmed-consistent |
| Empty searches | 229 zero-hit searches, each with a corresponding map entry |
| Class/store totals | old/final 60; old/r1 172; old/r0 78; new/final 1,396; variant/final 548 |
| Full-text verification | All 885 independent sweeps reproduce the receipt's hits, complete text and exit classification |
| Live sample | 15 `rg -F -n` searches across old/new/variant and hit/zero-hit values agree, including `parents[1]`, `VALIDSIG`, `host key changed`, `LC_ALL=C`, `reload` and `CLI step` |
| Current plan SHA-256 | `144f73d372b9be54288083ed0fb9a38d15b78e2b5c14c81de92935cdaef4c873` |
| Current task SHA-256 | `1926f915180848868ba825352bd50b541b195cd97cb65953775b8d893b6b6729` |

The claimed counts in `census-summary.txt` and `census-verify.txt` agree. Both current hashes agree with the correction log, raw receipt and `final-hashes.txt`. The historical r0 snapshot is treated as the declared census input, not as independently authenticated history; that distinction creates no author-forgery finding. Audit scripts/results are in `review scratch C:/Temp/zorivest/usb-kit-plan/review-r4/`.

### Scope addition, decisions, usability and complexity

**The four approved additions are represented in executable work.** WP-U5b/AC-31 (`plan:746-766`, `task:52`) preserve the existing pin, entry, block and known-host line on a changed key, count that record as failed, and continue the others; `--no-test` does not bypass the pin refusal. Same-key reruns/new names remain allowed. Record retire (`plan:245-255`, AC-27 `:666`, `:723`, A-12 `:1211`) applies the same pre-change name-clash/no-key rule on both platforms and preserves unrelated records. Fingerprints precede a successful record (`:641-642`, `:698-707`); failure leaves the current record retired. WP-U7/AC-21 and row 9 (`:857-867`, `task:56`) carry the compare, unknown-name, unique-name, reachability, repeat-import and custody instructions. No README change has been falsely claimed. The SHA256 key-blob convention agrees with [OpenSSH's fingerprint implementation](https://raw.githubusercontent.com/openssh/openssh-portable/master/sshkey.c) and [ssh-keygen's manual](https://raw.githubusercontent.com/openssh/openssh-portable/master/ssh-keygen.1).

**D-1/D-2 stay ruled A.** The records accurately preserve the human's 2026-11-08 words and the coordinator relay. Comparison with the pre-correction briefs shows the same fixed helper verbs/root boundary and the same installer-before-binary-verification timing. `NOSETENV`, `!env_check`, refusal of unproved policy and the account-context probe implement the promised clean environment; they do not select a different privilege option. F-021 is a fixture note inside A, not grounds to re-decide A. The per-platform census repairs D-2 applicability without altering its accepted residual. There is no new D-1/D-2 confirmation gate in this review.

| Target or declared limit | Judgment and concrete effect |
|---|---|
| Ubuntu Desktop, Avahi and DHCP, initially inactive UFW | **Defect F-022.** A first stop is predictable on normal sockets. Manual enable plus rerun does not satisfy the present unconditional post-setup listener pass. UFW's loopback DNS stub is different: the loopback exclusion correctly passes it. |
| Ubuntu Desktop with firewalld | **Defect F-022** when initially stopped with the same sockets. Running firewalld avoids the first-enable guard, but the live socket requirement remains; **F-023** additionally affects divergent target stores. |
| macOS mDNSResponder and application firewall | **Accepted residual.** No Linux Listener check/`ss` is used on macOS (`plan:620`, `:950`). mDNSResponder's UDP 5353 therefore does not create the Linux stop. The kit enables Remote Login, changes no macOS firewall, and discloses the key's `from=` as its network restriction (`:152`). Normal sharing/firewall operation is supported by Apple's docs; an explicitly blocked service remains a human setting/import failure, not proof that every Mac stops. [Apple mDNS implementation](https://github.com/apple-oss-distributions/mDNSResponder), [Apple sharing/firewall behavior](https://support.apple.com/en-gb/guide/mac-help/mh34041/mac). |
| Windows | **No new universal stop found.** A physical Private/Domain network satisfies WP-U4; Public physical networks deliberately require a human category choice. Virtual Public adapters do not block the normal physical-network path. OpenSSH capability/key creation precede the final fingerprint. A same-name record with no existing local key deliberately stops before installation; that is collision protection, not a first-run failure on an empty drive. |
| Inactive UFW does not report its saved rules until enable | **Accepted residual.** The post-enable report/live gate can expose the retained rule for the human. It is not an assertion that the unknown rules were removed. F-022 must still make the ordinary first-enable/recovery path usable. |
| Source-derived sudo/ss fixtures; real forms deferred to rows 13/14 | **Source-fixture note F-021.** The source already establishes the positive tag order; this should be corrected before writing fixtures. Other unobserved platform output remains honestly disclosed, with required live checks rather than claimed success. |
| Any foreign firewalld source binding or DROP/REJECT target stops | **Accepted conditional stop.** Stock target-zone rules can complete without foreign sources; customized conflicting classification is a reason to stop. The runtime/permanent observable failure is F-023, not a demand to model every priority. |
| Symlinks, unsafe helper parents, unusual sudo policy | **Accepted conditional stops.** Ordinary real home/.ssh paths and root-owned nonwritable parents are supported. The chosen no-symlink rule is explicit and testable. Foreign command/runas defaults may need human cleanup, but there is no evidence they exist on every stock target. F-021 warns against turning its fixture spelling into a literal own-rule comparison. |
| Row-7a marker drift after restructuring | **Accepted residual.** A changed/missing marker refuses the row; the prescribed refactor keeps the named functions. This is a repairable state inconsistency, not a silent retained-platform bypass. |
| First import has no previous pin | **Accepted residual for records.** The human comparison and unknown-name check remain the stated trust mechanism. No signed records or `--expect` list is demanded. See the separate code-integrity observation below. |
| Six plan rounds share the original token budget | **Accepted procedural limit.** The current human extended rounds only, and the records correctly retain the token cap and unchanged execution cap. |

**Complexity:** removing selector equivalence, Unix source-set comparison, UDP traffic modelling and symlink dereferencing genuinely narrows the behaviours the kit must implement. The plan text itself grew from 1,361 to 1,406 lines; task text remains 108 lines/43 rows. Growth alone is not a defect. F-021 is a small fixture/normalization correction, not evidence that a larger sudo parser is needed. F-022 shows where an unconditional fail-closed predicate outlives the transition it was intended to guard. F-023 needs an effective-state query, not a new zone-priority model. No preference-only complexity finding is raised.

### Out-of-Contract Observation

- The multi-member writable drive also carries elevated code: `fleet_usb.py:75-83` copies scripts/launchers once; `Setup Mac.command:4-5`, `Setup Linux.desktop:7` and `Setup Windows.cmd:9` execute them from that drive, and the planned helper is copied there too. A compromised visited member can alter that code for the next member while leaving both expected fingerprints unchanged, causing root/administrator execution on the next machine. The four approved record safeguards do not authenticate the program printing the fingerprint. The current exclusion concerns signed **records** (`plan:1003`), and this review does not invent a mandatory signing task; the broader executable risk should be made explicit for the human, or addressed with an independently trusted/read-only execution source. A self-check and hash list on the same writable drive are not an independent reference. This observation is not counted as a blocker or as a defect in the approved four-item record scope.

### Full coverage census

Both plan files and all round-3 changed text were read. A before/current line diff was used to identify each change, including complete long AC/table lines. The following matrices identify the reviewed contract surfaces; a coverage entry does not claim that pending implementation or new AC tests ran.

| Work package / all 31 ACs | Result of review |
|---|---|
| WP-U1 — AC-1, AC-2, AC-3 | Both constant consumers, manifest/hello checks and capability producer traced in `fleet.py`; explicit test expectation change and human hub/member update order retained. No new defect. |
| WP-U2 — AC-4, AC-5, AC-6, AC-7, AC-12, AC-28 | Load guards, explicit seams, Windows 5.1, bash 3.2/LF, characterization exception and all locator layouts remain coherent. Existing scripts parse; new tests/helper are scheduled, not falsely claimed present. |
| WP-U3 — AC-8, AC-9, AC-10, AC-11, AC-26 | Helper path/parent checks, fixed verbs/argv, package grammar, trusted environment and admin outcomes traced. F-001/F-015 exploit routes fixed; new second-read comparison is F-021. |
| WP-U4 — AC-13 | Effective-store Windows rule/filter/profile report, physical-network preflight and encoded shared report reviewed. No new defect or reason to weaken the Public-network gate. |
| WP-U5 — AC-14 Unix, AC-15, AC-16, AC-27 Unix | Source/offline/permanence controls, explicit no-symlink rule, old-record/clash handling, key-auth/drop-in rollback and fingerprint order reviewed. New failures F-022/F-023; no reopening of old rollback or source-binding findings. |
| WP-U5w — AC-14 Windows, AC-17, AC-27 Windows | Same clash semantics, key-auth before block, first/rerun rollback, restart handling and fingerprint before record. No new defect. |
| WP-U5b — AC-18, AC-31 | Probe is after admin connection, rejects non-publickey method lists and has an intentional no-test path; changed-pin refusal is before writes and applies even without the probe. Multi-record continuation/preservation is explicit. |
| WP-U6 — AC-19, AC-20 | Image signature/status/hash/exact-name checks remain before disk mutation. D-2's two-platform applicability is fixed; signer discovery remains an execution probe with a real stop if unavailable. No vendor-install path was run in this review. |
| WP-U7 — AC-21 | All five docs are scheduled, including the four-item addition's README instructions; stale current READMEs are pending work, not false completion. |
| WP-U8 — AC-22, AC-23, AC-24, AC-25, AC-29, AC-30 | Baseline adapter, red evidence, inventory privacy, full-state byte identity and live call chains reviewed. AC-24 has F-022/F-023, and the shared sudo parser has F-021. No new completeness predicate or author-forgery demand is introduced. |

| All 22 Named definitions | Review result |
|---|---|
| Kit; Drive folder | Scope/data locations agree with prepare and task rows. |
| Helper; Mode reader; Sudoers file | Ownership/physical parents, platform stat forms, startup and child environments agree. The source-fixture tag-order note is F-021. |
| Drop-in; Marked block; Key-auth check; Password-off check | Effective key settings precede password-off; rollback distinguishes pre/post reload; known Match/from limits remain disclosed. No new defect. |
| Record retire | Same host-key/name rule on both systems, no-key clash stop and own-key retirement align with AC-27. |
| Listener check | Unsafe exceptions removed; normal-desktop/live conflict is F-022. |
| Firewalld rules; Firewalld checks; SSH rule report | Source-bound drop and neutral source-specific report fixed. Permanent/runtime target substitution is F-023. |
| Member subnets | Record/firewall/from exclusions agree; VPN stays; zero subnet stops. |
| Load guard; Git bash; Stub folder | Test seams, locator layouts and stopped-daemon stub have scheduled producers; current bash parse succeeds. |
| Admin check; Outcomes; Probe; Console guard | Unix/Windows outcome mappings, no-test semantics and intentionally bounded console guard retained. No new defect. |

| All 43 task rows | Review result |
|---|---|
| PC; 0 | Human-only commit/dirty-file boundary retained. Both current CLI flags are observed; no Git write was performed. |
| 1 | Baseline/new checkers and their AC-29/30 selftests are explicitly scheduled. Existing peer checker/Pester wrapper and core validators exist. |
| 2; 2a | Constants/test change and human fleet update stay ordered. |
| 3 | Testable restructuring and red/guard exceptions cover both platforms and the new helper when added. |
| 3a; 4 | Typed A gate and dependency correct; F-021 affects the new policy parser. |
| 5 | Windows profile/rule report deliverable and tests present in task scope. |
| 6; 6a | Twelve-step Unix and ordered Windows changes align with corrected clash/fingerprint ACs; F-022/F-023 affect Unix firewall work. |
| 7 | Probe, fingerprint and pin-refusal work now includes AC-31 in red/green checks. |
| 7a; 8; 8a | D-2 flag/ruling checks verified in all platform states; image and retained-platform binary checks remain separate and human-ruling bound. |
| 9; 10; 11 | Five docs, targeted/regression and package/privacy gates are scheduled coherently. |
| 12; 13; 14; 15 | Explicit human live rows; no remote action authorized by this review. Row 13 has F-022/F-023; both Unix live paths must handle the source-derived form noted in F-021. BUILD_PLAN absence is correctly an audit result. |
| H1-1; H1-2; H1-3; H1-4 | Completion, fresh full/state binding and two justified no-op rows retained. |
| H1-5; H1-6; H1-6a; H1-6b | Existing templates/validators, handoff AC coverage and byte-bound durable evidence precede independent review. |
| H1-7; H1-7a; H1-7b | Independent execution-review dispatch/state/approval sequence retains its six-round cap. No self-approval or plan-to-execution transition is implied. |
| H2-1; H2-2; H2-3; H2-3a; H2-3b; H2-3c; H2-4 | Reflection/metrics/no-op bases, explicit maintainer issue-store paths and final privacy scan remain aligned. |
| H2-5; COMMIT; H2-6 | Human commit control and author-address check remain explicit; no attribution-trailer finding. Final status update remains last. |

All 43 rows are unchecked; no correlated implementation handoff exists. Referenced executable paths either exist or are explicitly scheduled. The absent BUILD_PLAN and MEU registry are intentional negative checks, not missing executables. All exclusions in the Out of Scope table have a stated source/scope basis; none conceals an unscheduled MEU deferral. Named definitions govern the abbreviated repeats; the materially different runtime/permanent behaviour is reported once as F-023, not as multiple repeated-literal findings.

### Verification, boundaries and checklist

All local launches used `rtk`/`rtk proxy`. Read-only models, public-source copies and receipts are under `review scratch C:/Temp/zorivest/usb-kit-plan/review-r4/`. No setup, installer, fleet hub/member/run, USB prepare/import, SSH, sudo, live firewall operation, credential read, or Git write was performed. Existing test suites exercise their local harnesses; no hub/member was contacted. The four separately dirty kit files were read only.

| Executed check | Result / decisive output |
|---|---|
| `rtk proxy python -X utf8 <review scratch>/audit.py` | Exit 0; all 885 sweeps, 2,254 dispositions, 229 zeros, hashes and 15 live samples agree. |
| `rtk proxy python core/tools/lint_task_contract.py --task docs/execution/plans/2026-11-07-usb-kit-hardening/task.md` | Exit 0; 43 rows, 10 columns, 41 fully checked, two view-file exemptions, acyclic dependencies. |
| `rtk proxy python -X utf8 <review scratch>/check_contract.py` | Exit 0 after classifying the two intentionally absent negative-check paths; 43 unchecked rows, 31 ACs, 22 definitions, no implementation handoff, no unscheduled missing executable. |
| `rtk proxy powershell -NoProfile -File <review scratch>/parse.ps1` | Exit 0; 44 validation snippets and two current PowerShell kit files parse under Windows PowerShell 5.1, zero errors. |
| Current `setup-unix.sh`, Git for Windows bash `-n` via `rtk proxy` | Exit 0; parse only. |
| `rtk proxy python -X utf8 <review scratch>/counterexamples.py` | Exit 0; actual row-7a validator: 12 expected outcomes; source-derived sudo tag mismatch and written listener/target counterexamples reproduced as models. |
| Existing `SetupMember.Tests.ps1`, through the existing fleet-agents `run_pester.ps1` | Exit 0; 65 passed, zero failed/skipped/inconclusive/not-run; wrapper selfchecks passed. |
| Existing four fleet pytest files (`-B -m pytest`, cache disabled, scratch basetemp) | Stopped by the reviewer before completion; partial progress only, wrapper exit 1 after cancellation. No full-suite pass or assertion-failure result is claimed. A subsequent targeted existing expected-set test passed: `test_fleet_agent.py::test_ac32_forbidden_commands_are_unchanged`, 1 passed in 0.55s (exit 0). |

```json
{
  "schema_version": "evidence.v1",
  "id": "R4-CENSUS",
  "phase": "static",
  "command": "rtk proxy python -X utf8 C:/Temp/zorivest/usb-kit-plan/review-r4/audit.py",
  "exit_code": 0,
  "result": "pass",
  "observed": "885 independent sweeps; 2254 receipt hits equal 2254 per-hit dispositions; 2121 updated and 133 confirmed-consistent; 229 zero-hit searches; complete source text, both input hashes and 15 current literal rg samples agree."
}
```

```json
{
  "schema_version": "evidence.v1",
  "id": "R4-COVERAGE",
  "phase": "manual",
  "procedure": "Read both corrected plan files, round-3 findings/corrections and all changed text; trace all 43 task rows, 31 ACs, 22 Named definitions, decisions, limits and exclusions against current code, peer validators and cited primary sources; attempt the stated refutations. Distinguish read-only contract models from executed existing checks and unavailable live observations.",
  "observer": "Codex",
  "command": null,
  "exit_code": null,
  "result": "fail",
  "observed": "PR-6 passes. The eight requested prior findings are fixed as counterexamples; two new High operational/control defects remain: normal-desktop listener/live-gate conflict and permanent-target substitution for runtime policy. A source-fixture tag-order note is Low and nonblocking. D-1/D-2 accurately remain chosen A. No new implementation or live success is claimed."
}
```

| Check | Result | Evidence |
|---|---|---|
| PR-1 | pass | All 43 rows align with WP-U1 through WP-U8, both platform halves, AC-31 and the README addition. |
| PR-2 | pass | 43 unchecked rows; implementation handoff absent; four dirty kit files are pre-existing separate work. |
| PR-3 | pass | Task-contract lint passes; owners, outputs, commands and dependencies present. |
| PR-4 | fail | F-022 demonstrates ordinary desktop/live evidence cannot satisfy the written checks. Parse/contract checks pass but do not refute them. |
| PR-5 | pass | ACs and A/D decisions carry source classifications; human's current ruling is accepted as the authority. |
| PR-6 | pass | Independent full receipt/disposition/hash audit and 15 live sample sweeps agree. |
| PR-7 | pass | Exclusions have evidenced scope bases; no unscheduled MEU deferral or concealed missing deliverable found. |
| PR-8 | fail | F-023 traces the effective-target report to a permanent-store producer; runtime ACCEPT survives an empty report. |
| PR-9 | pass | Named policies are authoritative; materially different target-store semantics are counted once under F-023. |
| DR-1 | pass | Corrections are plan text; current kit and pending tasks are not represented as implemented. |
| DR-2 | pass | Independently audited old/new/variant census accounts for every retained old literal. |
| DR-3 | pass | Renamed report and new AC-31 references propagate to tasks, files, counters and README work. |
| DR-4 | fail | Positive sudo fixture and unconditional desktop live check are wrong; divergent target-store negative case is missing. |
| DR-5 | pass | Exact commands, source traces, hashes, counts and durable observations retained; models clearly labelled. |
| DR-6 | fail | Desktop recovery conflicts with AC-24; live target claim reads the permanent store. F-021 is a nonblocking fixture correction. |
| DR-7 | pass | Current hashes/counts reproduced; no live success claimed and no unrun new AC reported as passing. |
| DR-8 | pass | D-1/D-2 risks stay disclosed and ruled A; this review explicitly refuses completion and distinguishes the broader writable-code observation. |

### Verdict

`changes_required`. Correct **F-022 and F-023 before execution**; correct F-021 as a nonblocking source-fixture note through `/plan-corrections`, preserving the human's A rulings and the six-round cap. Do not restore the unsafe UDP exceptions, source-set model or selector-equivalence parser to resolve these findings. PR-6 passes; the refusal rests on concrete delivery failures. This round authorizes no execution, member change, commit or push.

```json
{
  "schema_version": "review-verdict.v1",
  "date": "2026-11-08",
  "review_mode": "plan",
  "target_plan": "docs/execution/plans/2026-11-07-usb-kit-hardening",
  "agent": "Codex",
  "requested_verbosity": "detailed",
  "verdict": "changes_required",
  "summary": "Round 4 of 6: PR-6 passes. F-022 and F-023 are High and require correction before execution: the Ubuntu Desktop listener/live-gate dead end and permanent firewalld target queries used as runtime evidence. F-021 is a Low, nonblocking sudo fixture correction. The eight requested prior findings are fixed as counterexamples. D-1/D-2 accurately remain ruled A. Two review rounds remain. Only the rolling review is updated.",
  "findings": [
    {
      "id": "F-022",
      "severity": "High",
      "confidence": "High",
      "finding": "The TCP-22-only listener check stops ordinary Avahi/DHCP sockets before first enable; AC-24 requires the same real socket text to pass after setup. Manual firewall enable leaves those sockets present, so the stated Ubuntu Desktop target cannot pass the required live gate with its normal services (PR-4).",
      "file_line": "docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:256-261; :891-895; :949; task.md:60",
      "recommendation": "Specify and test a usable first-enable/resume path, and distinguish live output-format parsing from the first-enable safety decision. Keep unsafe port-only UDP exemptions removed.",
      "status": "open"
    },
    {
      "id": "F-023",
      "severity": "High",
      "confidence": "High",
      "finding": "mechanism: permanent-target-substituted-for-runtime-policy. The target stop/report query --permanent --get-target. Runtime ACCEPT with permanent default therefore survives an empty SSH rule report and the narrow-rule checks while outside-subnet SSH remains allowed (PR-8, A-4, AC-24).",
      "file_line": "docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:266-287; :291-294; :949; task.md:50",
      "recommendation": "Observe runtime targets separately before mutation and in the report/live gate, using runtime zone settings or list-all; test divergent runtime/permanent ACCEPT and DROP without reloading.",
      "status": "open"
    },
    {
      "id": "F-021",
      "severity": "Low",
      "confidence": "High",
      "finding": "The positive sudo rerun fixture spells NOPASSWD before NOSETENV, while the cited sudo formatter emits NOSETENV first. A literal comparison would stop a safe setup, but semantic matching can already satisfy A-18; this is a nonblocking fixture correction.",
      "file_line": "docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:507; :1271; task.md:48",
      "recommendation": "Use the actual formatter output for the positive fixture and compare tag values independently of display order.",
      "status": "open"
    }
  ],
  "checklist_results": [
    {
      "check": "PR-1",
      "result": "pass",
      "evidence": "All 43 rows align with WP-U1 through WP-U8, both platform halves, AC-31 and the README addition."
    },
    {
      "check": "PR-2",
      "result": "pass",
      "evidence": "43 unchecked rows; implementation handoff absent; four dirty kit files are pre-existing separate work."
    },
    {
      "check": "PR-3",
      "result": "pass",
      "evidence": "Task-contract lint passes; owners, outputs, commands and dependencies present."
    },
    {
      "check": "PR-4",
      "result": "fail",
      "evidence": "F-022 demonstrates ordinary desktop/live evidence cannot satisfy the written checks. Parse/contract checks pass but do not refute them."
    },
    {
      "check": "PR-5",
      "result": "pass",
      "evidence": "ACs and A/D decisions carry source classifications; human's current ruling is accepted as the authority."
    },
    {
      "check": "PR-6",
      "result": "pass",
      "evidence": "Independent full receipt/disposition/hash audit and 15 live sample sweeps agree."
    },
    {
      "check": "PR-7",
      "result": "pass",
      "evidence": "Exclusions have evidenced scope bases; no unscheduled MEU deferral or concealed missing deliverable found."
    },
    {
      "check": "PR-8",
      "result": "fail",
      "evidence": "F-023 traces the effective-target report to a permanent-store producer; runtime ACCEPT survives an empty report."
    },
    {
      "check": "PR-9",
      "result": "pass",
      "evidence": "Named policies are authoritative; materially different target-store semantics are counted once under F-023."
    },
    {
      "check": "DR-1",
      "result": "pass",
      "evidence": "Corrections are plan text; current kit and pending tasks are not represented as implemented."
    },
    {
      "check": "DR-2",
      "result": "pass",
      "evidence": "Independently audited old/new/variant census accounts for every retained old literal."
    },
    {
      "check": "DR-3",
      "result": "pass",
      "evidence": "Renamed report and new AC-31 references propagate to tasks, files, counters and README work."
    },
    {
      "check": "DR-4",
      "result": "fail",
      "evidence": "Positive sudo fixture and unconditional desktop live check are wrong; divergent target-store negative case is missing."
    },
    {
      "check": "DR-5",
      "result": "pass",
      "evidence": "Exact commands, source traces, hashes, counts and durable observations retained; models clearly labelled."
    },
    {
      "check": "DR-6",
      "result": "fail",
      "evidence": "Desktop recovery conflicts with AC-24; live target claim reads the permanent store. F-021 is a nonblocking fixture correction."
    },
    {
      "check": "DR-7",
      "result": "pass",
      "evidence": "Current hashes/counts reproduced; no live success claimed and no unrun new AC reported as passing."
    },
    {
      "check": "DR-8",
      "result": "pass",
      "evidence": "D-1/D-2 risks stay disclosed and ruled A; this review explicitly refuses completion and distinguishes the broader writable-code observation."
    }
  ]
}
```

🕐 Completed: 2026-11-08 10:47 (EST)

## Corrections Applied — 2026-11-08, round 4

Applied by the plan's author through `/plan-corrections`. This section is not an approval. All earlier text in this file is unchanged, except the frontmatter `verdict:` value, which `/plan-corrections` sets to `corrections_applied`; `findings_count:` stays 3. Only an independent reviewer can set `approved`.

This pass covers F-021 to F-023 of round 4 and the reviewer's out-of-contract observation on the code that the drive carries. Each finding was checked against the cited plan lines and the primary sources first. All three held, and none is dismissed. The rule for this pass: the setup fails closed and stops for the human, and the plan stays small. No UDP exception came back, no zone-priority model was added, and the observation got documentation only, with no code task. Line numbers are for the final files: `plan` is `implementation-plan.md` and `task` is `task.md`.

Direction in this pass:

- **Approach.** The coordinator's brief: fail closed and stop for the human; keep the plan small; correct F-022 and F-023 without the removed UDP exceptions and without a zone-priority model; treat the observation as documentation only.
- **D-1 and D-2 stay ruled A.** As relayed ("recoomendations for D-1 D-2 accepted", 2026-11-08). The D-1 and D-2 Decision Log entries, both Decision Briefs (plan:1320-1366, :1368-1389), the sudoers rule line (plan:203) and rows 3a and 7a (task:47, :53) are byte-identical to the text before this pass (`46-d1-d2.txt`). F-021 changes only a test sample and states how A-18 compares the printed tags. Option A's boundary (`NOSETENV:`, `!env_check`, the `LD_PRELOAD=` probe) is unchanged.
- **Review rounds.** The plan loop stays at 6 rounds (plan:89-90). This is the round-4 correction pass; two review rounds remain.

| Item | Disposition | Correction | Where | Evidence |
|---|---|---|---|---|
| F-022 | fixed | The Listener check runs only when the setup itself turns the firewall on: before `ufw --force enable` on an inactive `ufw`, and before `systemctl enable --now firewalld` on a stopped `firewalld`. An active `ufw` and a running `firewalld` get none. A stop prints each socket's Netid, address and port, and the command that turns the firewall on, `sudo ufw enable` or `sudo systemctl enable --now firewalld`. The human checks those services, runs that command at the screen and runs the setup again; the rerun finds the firewall active, so no Listener check runs, and the kit's rules from the first run are found and not added twice. The parser is now its own function, `parse_listeners`; `check_listeners` holds the enable decision. The live check (row 13, AC-24) uses only `parse_listeners`, as a format check: the mDNS and DHCP client sockets on an active firewall do not fail it, an inactive firewall still does, and a line the parser cannot read fails it. AC-15 adds the stock `avahi-daemon` socket `udp UNCONN 0 0 0.0.0.0:5353 0.0.0.0:*` and a DHCP client socket on `0.0.0.0%wlan0:68`, each stopping a first enable under an inactive `ufw` and under a stopped `firewalld` with the enable command printed, and a rerun on an active `ufw` and on a running `firewalld` with the same sockets, which makes no `ss` call and passes. AC-15's `ss` form note now names row 13 only, because macOS has no `ss`. The README work (WP-U7, AC-21, row 9) adds the Listener-stop rerun steps, and AC-21 fails a `usb/README.md` without `sudo ufw enable`. The TCP-22-only exception stays; no UDP exception returns. | plan:122-127 (User Review Required 5), :263-276 (Listener check), :646-655 (step 7), :676, :690 (AC-15), :706, :893-895 (WP-U7), :901 (AC-21), :910, :925-931 (WP-U8), :986 (AC-24), :1010-1014 (stop 6), :1239-1243 (A-11), :1414; task:50 (row 6), :56 (row 9), :60 (row 13) | avahi `avahi-core/socket.c`: the IPv4 mDNS socket binds port 5353 with its address left zero, the wildcard address (`23-src-confirm.txt`). Ubuntu security documentation, firewall page: `ufw` "is available in Ubuntu, but disabled by default" (`22-src-grep.txt`). So a first setup on a stock desktop stops at the Listener check, and the live gate must not repeat that enable decision. |
| F-023 | fixed | The setup reads each target zone's target from each store on its own. The runtime target is the one `firewall-cmd --zone=<zone> --list-all` line whose first word is `target:`. The permanent target is `firewall-cmd --permanent --zone=<zone> --get-target`, or `firewall-offline-cmd --zone=<zone> --get-target` with the daemon stopped, when there is no runtime target yet. A target zone stops the setup, with the zone and each target named, unless every target read for it is `default`; a `--list-all` with no `target:` line, or with more than one, stops it too. So the kit never acts on a runtime target that differs from the permanent one, as a `--permanent --set-target` without `--reload` leaves it, and the `REJECT` and `%%REJECT%%` spellings need no map. The Firewalld checks repeat the stop on the runtime zones with both reads. The SSH rule report lists a zone whose runtime or permanent target is `ACCEPT`, `status` shows both targets, and AC-24 needs both to be `default`. AC-15 adds the two negative cases: a running-daemon target zone whose `--list-all` shows `target: ACCEPT` while `--permanent --get-target` prints `default`, and one with `target: DROP` and `default`, each with no `--reload` in the stub log, each stopping before any runtime change with the zone and both targets named. AC-15 also adds a report case for each direction and a pass when both targets are `default`. AC-24's selftest fails the runtime `ACCEPT` with permanent `default`. No zone-priority model was added. | plan:283-294 (Firewalld rules), :306-310 (Firewalld checks), :317-318 (SSH rule report), :488 (`status`), :679, :680, :690 (AC-15), :707, :986 (AC-24), :1010-1014 (stop 6), :1413; task:50 (row 6) | firewalld `src/firewall-cmd.in`: `get_target` is in `options_permanent_only`, which fails without `--permanent`; the permanent print maps `%%REJECT%%` to `REJECT`; runtime `--list-all` prints `fw.getZoneSettings(z)` (`23-src-confirm.txt`). `src/firewall/command.py` `print_zone_policy_info` prints the `target:` line, and `src/firewall/core/fw_zone.py` `get_config_with_settings_dict` gives the zone as the daemon loaded it. |
| F-021 | fixed | The positive AC-26 rerun sample now shows the kit's rule as `sudoers_format_cmndspec()` prints it, `(root) NOSETENV: NOPASSWD: /opt/fleet-admin/fleet-admin`, and a second sample with the sudoers file's order, `NOPASSWD: NOSETENV:`, also passes, because A-18 compares the tags as a set and not in their printed order. Row 4 states the set comparison for the second read's last-entry check. The sudoers file text is unchanged. | plan:531 (AC-26), :1309, :1312 (A-18), :1408; task:48 (row 4) | sudo `plugins/sudoers/fmtsudoers.c` `sudoers_format_cmndspec()`: the `SETENV: `/`NOSETENV: ` append comes before the `NOPASSWD: `/`PASSWD: ` append, at lines 281 and 287 of the round-4 review's copy and lines 270 and 276 of the round-2 copy (`27-fmt-src.txt`). |
| Observation (code on the drive) | documented | A new Risks bullet: the drive also carries the setup scripts, the launchers and the helper, which run as administrator or root. A machine that the drive visits can change them for the next member and still print the expected fingerprints, and the kit does not check it. So one drive serves several members only when every member is equally trusted; otherwise `fleet_usb.py prepare` runs again on the hub before each member. The WP-U7 text for `usb/README.md` says the same, and states that `prepare` rewrites the scripts, the launchers, the helper, the README and `hub.pub` from the hub's copy and leaves `members/` and any other file, so the fingerprint compare still applies. AC-21 fails a `usb/README.md` without the words `equally trusted`; row 9 and the Files table name the one-drive trust rule. The Out of Scope row now also excludes signed or hash-checked code on the drive, because a hash list or self-check on the same writable drive is no independent reference. No code task was added. | plan:168-171 (Risks), :884-892 (WP-U7), :901 (AC-21), :910, :1041 (Out of Scope); task:56 (row 9) | `fleet_usb.py:66-83`: `prepare` writes each of `MEMBER_FILES` (`:26-27`, which holds `README.md`; row 4 adds `fleet-admin.sh`) and `hub.pub`, and makes `members/` only if it is missing. The reviewer's trace: `fleet_usb.py:75-83` and the three launchers run the scripts from the drive. |

**Blast-radius census:** 96 round-4 values declared, 456 values swept in all, 3137 sites found, 889 updated, 2248 confirmed consistent.

The 456 values are 157 old, 223 new and 76 variants. 352 carry from rounds 1 to 3. 96 are the round-4 values (35 old, 39 new, 22 variants); 4 of them (`ss -ltnuH`, `check_listeners`, `--reload` and `fmtsudoers.c`) were already carried, so each is swept once. 8 come from the code spans that a script derived from the round-4 diff (`derived-values.txt`). The 271 values that round 3 derived from its own diff are not derived again. No carried value had to move to old. The round-4 old values include the first-enable-only wording (`before a firewall that was off is enabled or started`, `each with the Listener check`), the old live-check wording (`passes the parsers`, `rows 13 and 14, which feed real output`), the target forms (`` `default` or `ACCEPT` ``, `a zone target of `ACCEPT``, `firewall-offline-cmd --get-target`), the old AC-26 sample (`its `NOPASSWD: NOSETENV:` line`) and the old README and Out of Scope wording. Each value is searched in two texts: `final`, and `r0`, the text before this pass (the round-3 output, whose hashes the round-4 recheck reproduced). The script ran 912 searches.

| Class | Target | Searches | Hits | Updated | Confirmed consistent | Zero-hit |
|---|---|---|---|---|---|---|
| old | final | 157 | 64 | 18 | 46 | 129 |
| old | r0 | 157 | 98 | 52 | 46 | 96 |
| new | final | 223 | 892 | 323 | 569 | 1 |
| new | r0 | 223 | 736 | 167 | 569 | 46 |
| variant | final | 76 | 715 | 206 | 509 | 2 |
| variant | r0 | 76 | 632 | 123 | 509 | 5 |
| **Total** | | **912** | **3137** | **889** | **2248** | **279** |

- Disposition is set against the paired line in the other text. `updated` means the paired line differs, so round 4 changed the line, or the line has no pair. `confirmed-consistent` means the paired line is the same and the line was read against the corrected text. The verifier checks the pairing for the 2973 hits that have a paired line.
- The 64 old-value hits in the final text each have a reason in the map's last column. Unresolved: 0. 46 are on lines that round 4 did not change, and keep their earlier reasons. 18 are on lines that round 4 changed; 4 of those are new hits, each in another sense: `the one line` at plan:283 (the runtime `target:` line, not the retired sudoers line), `firewall-cmd --permanent` at plan:286 (the read-only permanent target query), `--reload` at plan:293 (the human's no-reload change; the kit runs no reload), and `` `check_listeners` | Netid `` at plan:676 (the tail of the new owner cell, which names `parse_listeners` first).
- 34 of the 35 round-4 old values have zero final hits; the 35th is the owner-cell tail above.
- The zero-hit new value is `host key changed`, carried from round 3; the plan says `changed key`. The two zero-hit variants are `default if` and `Default if`, also carried. Each round-4 new value and variant is found in the final text.
- The read list holds 162 distinct final lines: 77 changed in round 4, and 85 unchanged lines that a round-4 value hits. This pass read all 162.

Receipts (`receipts in C:/Temp/zorivest/usb-kit-plan/corrections-r4/`):

- `census-receipt.txt`: every search, its exit code and each matching line in full.
- `disposition-map.txt`: one row per receipt hit, with the zero-hit rows; each row names its paired line in the other text.
- `census-summary.txt`, `derived-values.txt`, `read-list-r4.txt`, `census-verify.txt` and `final-hashes.txt`.
- `r0/` (the text before this pass) and `r0-hashes.txt`.
- `fetched/` and `fetched2/`: firewalld `firewall-cmd.in`, `command.py`, `fw_zone.py`, the server module, `firewall-offline-cmd.in` and both man pages, avahi `socket.c`, and the Ubuntu firewall page.
- The numbered receipts from `01-`: the source greps, the edit dry run and the applies (`30-dry.txt`, `31-apply.txt`, `38-apply-rewrap.txt`, and `49-review-dry.txt` and `50-review-apply.txt` for this section), the census runs, `46-d1-d2.txt` and `48-ac-count.txt`; and `lint-final.txt` and `privacy-final.txt`.
- `tools/`: the edit blocks of this pass, `apply_edits.py`, and the census, verify and D-1/D-2 check scripts.

**Verification:** `census_verify_r4.py` passes (`census-verify.txt`: sweeps 456, searches 912, receipt hits 3137, map rows 3137, zero-hit 279, paired-line checks 2973). It is the round-3 `census_verify.py` with two targets, an 11-cell map and the paired-line check added. It checks each hit against the whole file line, each search's exit code against its hits, an explicit zero-hit line, the receipt-to-map match, the dispositions, that no reason says UNRESOLVED, the four hash rows, and one final and one r0 search per sweep. `lint_task_contract.py` passes with 43 rows (`lint-final.txt`). The plan still has 31 ACs in 33 AC rows (AC-14 and AC-27 have two halves) and `AC_COUNT` 31 (`48-ac-count.txt`). The privacy scan of both plan files and this file, with the extra terms given only on the command line, finds 0 hits (`privacy-final.txt`). No AC was executed, because every correction is plan text and the tests do not exist yet.

Deviations from the reviewer's suggested shape:

- F-022: the first-enable path is a stop that prints the listeners and the enable command, then a human enable and rerun; the kit does not enable the firewall past a listener itself.
- F-023: the runtime target comes from `--list-all`, the reviewer's second named source. Only `default` passes, so a target zone with `ACCEPT`, such as the stock `trusted` zone, now stops the setup instead of only being reported; the round-3 text let `ACCEPT` through to the report.
- F-021: no wider sudo parser. The sudoers file keeps its order `NOPASSWD: NOSETENV:` (plan:203); only the sample and the comparison changed.
- Observation: documentation only, as directed; no signing, hash list or read-only source task.
- A last pass (`r4-plan-d.txt`) split one long WP-U8 line (plan:925-931) with no word changed.

Residual risks:

- The `--list-all` `target:` form comes from the firewalld sources, not from a live member. Row 13 sees firewalld only if that member runs it; a stock Ubuntu member uses `ufw`.
- A first setup on a stock Ubuntu Desktop stops at the Listener check, by design, and needs the human's enable and a rerun. Which traffic the enable cuts off is the human's choice; the kit does not prove it.
- The stock `trusted` zone now stops the setup when it is a target zone.
- In the stopped-firewalld branch, a zone that NetworkManager binds only after the start gets its targets read after the start, as it gets its rules (as in round 3).
- The code on the drive is protected only by the one-drive trust rule and a fresh `prepare` before each member. An extra file planted on the drive survives `prepare`, but no launcher runs it.
- The real sudo tag order is confirmed only by rows 13 and 14, and the real `ss` form only by row 13.
- `parse_listeners` is a new function name that row 6 creates.
- 6 plan rounds share the unchanged 10,500,000-token budget.

**Open human decisions:** none. D-1 and D-2 stay ruled A, as relayed. This pass adds no new human decision.

Corrected input SHA-256 values (`implementation-plan.md` has 1446 lines, 40 more than before this pass; `task.md` has 108 lines and 43 rows):

- `implementation-plan.md`: `58992688a800af1ab824a829b5963282283ce97b8f4c6482989ec991c50564c5`
- `task.md`: `6219e3eb010b809246d2272bf2356f3ebdbd0ca39241d9b590f5f475f82fb6a6`

Not resolved:

- No live firewalld member or Ubuntu Desktop was observed. The `target:` line form and the `avahi-daemon` socket form come from the sources, and rows 13 and 14 are the first real check.
- No independent census audit ran in this pass; the verifier above is the author's, adapted from round 3. The next reviewer can repeat the sweeps from `census-receipt.txt` and `r0/`.
- The current `usb/README.md` and `install-usb/README.md` belong to another session's uncommitted work and were not edited. The Listener-stop and one-drive trust text exists only as WP-U7 work for row 9.

🕐 Completed: 2026-11-08 11:43 (EST)


## Recheck (2026-11-08) — Round 5 of 6

Executing this plan should make the USB SSH kit usable on Windows, macOS and Linux, close the seven original gaps, and deliver the four approved record safeguards while stating the writable-drive risks honestly. The three round-4 findings are fixed; one new, supported defect remains in the proposed documentation: another `prepare` does not make a drive safe to carry between members with different trust levels.

**Verdict:** `changes_required`. **Round:** 5 of 6. Round 6 is the last under the human's 2026-11-08 instruction, "Add 3 more rounds"; a plan still unapproved there goes to the human. D-1 and D-2 remain ruled A. The human's reading at the plan-to-execution gate remains the terminating trust anchor.

### Findings

Here `plan` means `docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md`, `task` means its adjacent `task.md`, and kit source references are to the current files, which this review did not change.

| ID | Severity | Confidence | Blocking | Kind | Finding and failure | File:line | Recommendation | Status |
|---|---|---|---|---|---|---|---|---|
| F-024 | High | High | yes | behavior | The new guidance offers `prepare` before each member as the alternative to equally trusted members. `prepare` overwrites its fixed inventory and preserves every extra file. The Windows launcher invokes bare `powershell` from the drive; an extra `powershell.cmd` planted by a visited member survives that refresh and can be selected instead of Windows PowerShell on the next member. The prescribed workaround therefore still permits attacker code to run before the trusted setup and its fingerprint output. This is materially inaccurate safety guidance, not a demand to add code authentication. | `plan:168-171`, `:884-892`, `:901`, `:1041`; `task:56`; `.agent/fleet/usb/fleet_usb.py:73-83`; `.agent/fleet/usb/Setup Windows.cmd:6`, `:9`; `.agent/fleet/usb/README.md:31-35` | Correct the documentation only: do not describe another `prepare` into the same populated folder as sufficient for differently trusted members. Either limit reuse to equally trusted members and disclose this residual, or describe an independently clean reconstruction with explicit treatment of retained records. Keep the code exclusion honest and the `prepare` overwrite/preservation facts exact. | open |

**F-024 must be corrected before execution starts.** No other blocking finding or clerical correction note survived this pass. The violated contracts are PR-5 (the mitigation's claimed source basis must be true), PR-8 (a claimed control needs a real producer), DR-1/DR-6 (claim-to-state and canonical/source agreement), and WP-U7/AC-21's accurate risk documentation as requested by the coordinator.

#### F-024 — Refutation and concrete trace

The correction genuinely documents the original writable-code risk. Its `equally trusted` rule is useful, the facts that `prepare` overwrites the named scripts and preserves `members/` are true, and code authentication remains excluded by direction. Those facts do not establish the alternative introduced by "otherwise run `prepare` again".

The actual call chain is `fleet_usb.py main` (`:227-228`) → `prepare` (`:66-89`) → writes of `MEMBER_FILES` (`:75-81`) and `hub.pub` (`:83`). Row 4 adds the helper to that list (`task:48`); no row adds a directory purge or removal of other files. A previously visited member can plant `powershell.cmd` alongside the launchers. The documented next action is to double-click `Setup Windows.cmd` (`usb/README.md:31-35`; `task:59`). That launcher runs bare `powershell` for the elevation request (`:6`) and for the script invocation (`:9`). With the drive folder as the working directory, ordinary Windows command search can choose the planted command before PATH. The same mechanism can run in an already elevated console, and attacker code selected before the elevation request can relay the expected administrator prompt.

Microsoft explicitly documents that, when `NoDefaultCurrentDirectoryInExePath` is absent, cmd searches `.;%PATH%`. A local, harmless fixture containing only a marker-printing `powershell.cmd` was selected by `cmd /d /c powershell -NoProfile -Command ...` with that ordinary search configuration: exit 0, output `DRIVE_LOCAL_COMMAND_SELECTED`. The environment change applied only to the child probe; it changed no machine setting. No kit launcher, setup, `prepare`, `import`, sudo, SSH or elevation was run for this probe. The probe does not claim administrator execution was tested. [Microsoft command-search documentation](https://learn.microsoft.com/en-us/windows/win32/api/processenv/nf-processenv-needcurrentdirectoryforexepatha).

**Refutations checked:** rewriting `Setup Windows.cmd` does not remove the extra command; adding the helper to the inventory does not remove it; `-NoProfile` and `-ExecutionPolicy Bypass` are arguments after command selection; exFAT permits an ordinary `.cmd` file; fingerprints cannot authenticate the interpreter or program printing them. A host that explicitly disables current-directory search can avoid this example, but that is not a kit prerequisite or a stated effect of `prepare`. The benign fixture establishes the ordinary search failure, rather than assuming every Windows configuration has it.

This is a new false mitigation in the round-4 text, not a reopening of the earlier nonblocking demand for code integrity. A documentation-only correction is sufficient. No signing task, hash list, launcher patch or broader security architecture is required by this finding. The correction log's statement that an extra file survives but "no launcher runs it" (`review:1583`) is inaccurate for the same reason; earlier review/correction text is retained as history.

### Prior Pass Summary — F-021 to F-023

"Fixed" here means the corrected plan removes the counterexample. Implementation and the new AC tests remain pending.

| Finding | Round-5 result | Corrected plan and current-source evidence |
|---|---|---|
| F-021 | **Fixed** | `plan:531`, A-18 `:1309-1313`, `task:48`: the positive sample uses `(root) NOSETENV: NOPASSWD: /opt/fleet-admin/fleet-admin`, both orders pass, and the last-entry check requires exactly the two tag values as a set with the same root runas and command. The source's `sudoers_format_cmndspec()` emits NOSETENV before NOPASSWD (`fmtsudoers.c:280-287`). Missing NOSETENV and SETENV remain negatives. Current `setup-unix.sh:105-116` is still the old, scheduled-for-replacement block; no implemented parser is claimed. |
| F-022 | **Fixed** | `plan:263-276`, `:646-655`, `:676`, AC-15 `:690`, `:925-931`, AC-24 `:986`, A-11 `:1239-1243`; `task:50`, `:60`: both inactive-UFW and stopped-firewalld first enables still stop on Avahi/DHCP and print the enable command. Human review/enable plus a rerun takes the active branch and makes no listener-check call. The live row calls `parse_listeners` only for form, so the same sockets pass on an active firewall; the inactive-firewall negative, rule/report checks, password probe and admin checks remain. No UDP exception returned. Current `setup-unix.sh:54-63` lacks the proposed controls, consistently with row 6 being unstarted. |
| F-023 | **Fixed** | `plan:283-294`, `:306-310`, `:317-318`, `:488`, `:679-680`, AC-15 `:690`, AC-24 `:986`; `task:50`: runtime comes from the single `target:` line of runtime `--list-all`, permanent from the separate permanent query. Only `default` passes, with a missing/duplicate runtime line stopping too. The two divergent ACCEPT/default and DROP/default fixtures each stop before a runtime mutation and require both targets in the message; reload remains forbidden. The stopped branch uses only the offline permanent target before start, then reads runtime zones and both targets after start. |

#### Listener scope, recovery and live safety

The first-enable guard remains a real safety stop. The new stock-desktop fixtures are `udp UNCONN 0 0 0.0.0.0:5353 0.0.0.0:*` and DHCP on `0.0.0.0%wlan0:68`. Each stops both inactive `ufw` and stopped `firewalld` before enable/start; step 8's key, step 10's password change and step 12's new record have not run. The already installed firewall rules are queried on the rerun. Only the human can take the printed enable step. The same sockets then cease to be an attempted firewall transition and no longer cause the live-check dead end.

`parse_listeners` is a scheduled row-6 function, not an existing executable whose absence is ignored. Its separate `check_listeners` caller makes the distinction explicit in the definition, task, boundary inventory, fixtures, live mode and stop text. `plan:986` still requires an active firewall and actual subnet rules, an empty other-SSH-rule report, both password values off, the hub probe and the limited admin outcome. A malformed socket line still fails. Thus accepting normal sockets on an already active firewall removes no claimed safety check: first-enable safety guards the setup's transition, while the live gate checks the resulting policy. UDP 22, 68, 546, 5353 and 51820 remain negative first-enable examples, not safe-port exceptions.

Ubuntu's documentation confirms UFW is disabled by default, and Avahi's socket producer confirms its wildcard UDP mDNS bind. A contract model checked these cases and both resume branches; it is not a live Ubuntu observation or a test of code yet to be written. [Ubuntu firewall defaults](https://documentation.ubuntu.com/security/security-features/network/firewall/), [Avahi socket producer](https://raw.githubusercontent.com/avahi/avahi/master/avahi-core/socket.c).

#### Runtime and permanent firewalld observables

The independent source trace reaches the loaded zone, not the permanent configuration object:

1. `firewall-cmd.in:1234-1277`, `:1410-1411` classify `get_target` as permanent-only. The permanent branch prints the configured target (`:3121-3126`). Runtime `--list-all` instead calls `fw.getZoneSettings(z)` (`:4022-4029`).
2. The server's `getZoneSettings` calls `self.fw.zone.get_config_with_settings(zone)` (`server-firewalld.py:930-934`). That calls `get_config_with_settings_dict` (`fw_zone.py:476-506`), which exports `self.get_zone(zone)`, the daemon's loaded zone object. The local variable named `permanent` in that function is not a read of the daemon's separate on-disk config service. It normalizes the internal default target to `default`.
3. `command.py:502-512`, `:567` gets the target from those settings and prints `  target: <value>`; whitespace splitting therefore gives the required first word. The two-space indentation is not a parsing defect. The formatter is not localized here.
4. In the stopped branch, `firewall-offline-cmd.in:3010-3016`, `:3377-3379` reads zone settings from the offline config and calls `getTarget`. `client.py:235-243` normalizes the internal default target to `default`; the default zone does not accidentally stop as an internal sentinel. This branch has no runtime object to query. After start, the running checks supply it.

The [firewall-cmd man page](https://firewalld.org/documentation/man-pages/firewall-cmd.html) marks `--get-target` permanent-only and `--list-all` usable in either store. The [offline man page](https://firewalld.org/documentation/man-pages/firewall-offline-cmd.html) provides its zone `--get-target` without `--permanent` and restricts the tool to a stopped daemon. Both agree with the code.

To check the fixtures rather than just their wording, a scratch script extracted and executed the upstream pure `get_config_with_settings_dict`, `getTarget` and `print_zone_policy_info` methods with inert objects. Loaded runtime ACCEPT and DROP each produced the correct runtime line while the separate permanent value stayed `default`; both fail the written pre-mutation rule. Loaded default/permanent default passes. The reverse default/ACCEPT case stops and is reportable. Offline default passes; offline ACCEPT, DROP and both rejection spellings stop. Missing/duplicate runtime lines stop. No firewall client or daemon ran. These observations validate the observable and the proposed fixtures, not an unimplemented kit parser. [CLI source](https://raw.githubusercontent.com/firewalld/firewalld/main/src/firewall-cmd.in), [formatter](https://raw.githubusercontent.com/firewalld/firewalld/main/src/firewall/command.py), [loaded-zone producer](https://raw.githubusercontent.com/firewalld/firewalld/main/src/firewall/core/fw_zone.py), [client target normalization](https://raw.githubusercontent.com/firewalld/firewalld/main/src/firewall/client.py).

### Documentation, records and decisions

The overwrite/retention description itself is accurate: `prepare` writes the setup scripts, launchers, README and `hub.pub`, and row 4 will add the helper. It creates `members/` only if absent and does not delete records, `.old` records or any other extra file (`fleet_usb.py:73-83`). `import_records` still selects only `members/*.json` (`:176-177`), validates each record (`:188-192`) and preserves other names in the hub state (`:183-203`). A fresh `prepare` therefore loses no records; old `.json` records still participate in import, reachability and the planned pin refusal, and still require the human's fingerprint comparison. A rebuild into a genuinely empty folder would have different retention behavior and must not silently be presented as the existing `prepare` behavior.

The Risks bullet and WP-U7 correctly warn that a member can modify elevated code and spoof expected fingerprint output. AC-21's `equally trusted` requirement and row 9 correctly schedule that warning. The widened Out of Scope row correctly keeps code signing/hash checking outside this documentation-only pass. The specific claim that another `prepare` substitutes for that protection is the one inaccuracy, covered once by F-024. It does not justify expanding scope into a code fix or weakening the record safeguards.

**D-1 and D-2 remain ruled A, without a new decision.** Independent comparisons against the pre-correction snapshot find the two complete Decision Briefs, both Decision Log entries, rows 3a/7a and the sudoers rule byte-identical. The tag-set comparison changes representation handling only. The fixed verbs/root boundary, clean environment, account-context probe and installer-before-binary-verification timing remain as briefed. No round-4 change selects another option.

### PR-6 — independent census gate

**Pass before substantive review.** A new reviewer script parsed the raw receipt and map without importing or running the planner's census/verifier. It joined every hit by search id, class, target and `file:line`, preserving multiplicity; compared complete source lines; repeated every declared search against current and r0 files as a substring sweep; checked every zero-hit declaration and exit; and repeated 15 literal searches using live unfiltered `rtk proxy rg` against the current plan files.

| Check | Reproduced result |
|---|---|
| Values and searches | 456 distinct declared values; 912 searches over final and r0 |
| Hits and dispositions | 3,137 hits = 3,137 disposition rows; 889 updated + 2,248 confirmed-consistent |
| Empty searches | 279, each with a matching zero-hit map row |
| Class/store totals | old/final 64; old/r0 98; new/final 892; new/r0 736; variant/final 715; variant/r0 632 |
| Complete-text verification | All 912 independent source sweeps match the receipt; no missing, clipped or undispositioned hit |
| Live samples | All 15 agree, including `sudo ufw enable`, both listener function names, target queries, both divergent target examples, `equally trusted`, both sudo tag orders, UDP, reload and zero-hit values |
| Final plan SHA-256 | `58992688a800af1ab824a829b5963282283ce97b8f4c6482989ec991c50564c5` |
| Final task SHA-256 | `6219e3eb010b809246d2272bf2356f3ebdbd0ca39241d9b590f5f475f82fb6a6` |
| r0 plan SHA-256 | `144f73d372b9be54288083ed0fb9a38d15b78e2b5c14c81de92935cdaef4c873` |
| r0 task SHA-256 | `1926f915180848868ba825352bd50b541b195cd97cb65953775b8d893b6b6729` |

The totals agree with the correction log, `census-summary.txt`, `census-verify.txt` and `final-hashes.txt`. The hashes agree with the raw receipt and the log's input/output statements. r0 is the declared historical input, not independently authenticated history; no author-forgery concern is inferred. Reviewer scripts, source copies, source hashes and audit results are in `review scratch C:/Temp/zorivest/usb-kit-plan/review-r5/`.

### Usability and complexity

These are source/contract judgments about the proposed implementation. No live target or completed new kit implementation was observed.

| Target | Concrete path and result |
|---|---|
| Ordinary Ubuntu Desktop, inactive UFW, Avahi/DHCP | First enable deliberately stops, prints `sudo ufw enable`, and leaves key/password/record completion pending. After the human reviews services, enables and reruns, the active branch completes without repeating the listener decision; the same sockets satisfy the format-only live gate. Loopback DNS remains exempt by address. No remaining F-022 dead end. |
| Fedora-style host, running firewalld | A normal default-target zone with no foreign source binding receives each rule in runtime/permanent stores, loses the stock SSH service in each and passes without reload. mDNS/DHCP sockets do not invoke the first-enable guard. Other services/high ports remain as A-10 specifies. |
| Fedora-style host, stopped firewalld | Offline queries/changes precede the first-enable guard; sockets cause the printed human start and rerun. The active rerun resolves NetworkManager's runtime zones and applies the required pass there. With ordinary default targets this completes after that resume; runtime/permanent divergence or conflicting sources deliberately stop for the human. No unsupported offline runtime query remains. |
| macOS | No Linux firewall/listener/`ss` call. Existing Remote Login screen instructions cover a failed automatic enable; normal real home paths and safe helper parents support setup. Key-auth/drop-in checks and the source-correct sudo-tag comparison permit the live path. The absence of a macOS machine remains row 14's explicit human dependency, not evidence of a universal failure. |
| Windows | A physical Private/Domain network permits setup; a Public physical network has the existing stated human category step, while Public virtual adapters do not block a suitable physical network. Capability/key creation precedes fingerprint/record completion. F-024 affects the claim about reuse across differently trusted members, not a universal clean-drive setup failure. |

Customized SSH policies, foreign sudo defaults, intentional symlink homes, unsafe helper parents, changed-name/key records and non-default/conflicting firewall configurations retain explicit fail-closed stops. Missing CLI verification material remains Probe-1's already accepted stop under D-2 A. None proves that ordinary setup cannot complete; none is newly raised as a usability defect.

**Complexity:** the new parser/decision split resolves the demonstrated desktop failure and removes no actual policy check. Reading two firewalld stores and accepting only default avoids a target-equivalence or priority model. Comparing two sudo tags as a set is bounded. No preference-only complexity finding is raised. The one concrete failure is the inaccurate refresh workaround, F-024; it needs accurate prose, not additional code machinery.

### Full coverage census

Both plan files, the full round-4 changed text, all 43 rows, all 22 Named definitions, all 31 AC ids (33 rows including both AC-14 and AC-27 halves), decisions, stop conditions and exclusions were reviewed. All task statuses remain unchecked, the implementation handoff is absent, and the four dirty kit files remain separately owned work. The census does not claim new tests were run.

| Work package / complete AC coverage | Result |
|---|---|
| WP-U1 — AC-1, AC-2, AC-3 | Both constant consumers and capability producer in `fleet.py`, the existing expected-set change and human update/hello order align. No new defect. |
| WP-U2 — AC-4, AC-5, AC-6, AC-7, AC-12, AC-28 | Load seams, bash 3.2, LF, 5.1 parsing, guard/characterization exceptions and Git-root layouts remain aligned. Current script parsing passes; helper/new tests are scheduled, not falsely reported present. |
| WP-U3 — AC-8, AC-9, AC-10, AC-11, AC-26 | Fixed argv/package grammar, startup/tool environments, physical-path ownership, sudo second read/probe and admin outcomes remain; F-021 is fixed. No option-A change or reopened injection finding. |
| WP-U4 — AC-13 | Physical-network preflight, effective-store filters/profiles, reporting and encoded shared function remain consistent. No new universal stop or scope bypass demonstrated. |
| WP-U5 — AC-14 Unix, AC-15, AC-16, AC-27 Unix | Both firewall branches, target/source stops, first-enable resume, atomic key write, strict modes, key-auth/drop-in rollback and record/fingerprint order align. F-022/F-023 are fixed. |
| WP-U5w — AC-14 Windows, AC-17, AC-27 Windows | Guard, clash/retire, key before password block, restore/restart distinctions and fingerprint before record remain aligned. No new defect. |
| WP-U5b — AC-18, AC-31 | Probe follows admin connection; changed pins are refused even with `--no-test`; other records continue and the old entry/block/line are preserved. First-pin human comparison remains disclosed. |
| WP-U6 — AC-19, AC-20 | Image signature/status/exact-hash checks precede disk mutation; retained CLI halves and unavailable-verification stop remain under ruled A. No installer or disk command was run. |
| WP-U7 — AC-21 | All five docs and the new risk/resume text are scheduled. One materially false mitigation is F-024; the current READMEs are not represented as already corrected. |
| WP-U8 — AC-22, AC-23, AC-24, AC-25, AC-29, AC-30 | Baseline, negative live samples, privacy inventory, byte-bound full evidence and human live gates remain real scheduled deliverables. AC-24 now permits ordinary sockets without accepting an inactive or broad SSH policy. |

| All 22 Named definitions | Result |
|---|---|
| Kit; Drive folder | Scope/location match the code. `prepare`'s documentation implication, rather than these definitions, has F-024. |
| Helper; Mode reader; Sudoers file | Fixed privilege/environment and root-owned physical-parent constraints remain; F-021's output-order fix changes no grant. |
| Drop-in; Marked block; Key-auth check; Password-off check | Key usability precedes password-off, first/rerun snapshots and post-reload distinction remain, known Match/from limits are disclosed. |
| Record retire | Same-key retirement, no-key/different-key clash stop, old-name matching and other-record preservation remain consistent on both platforms. |
| Listener check | First-enable safety, human resume and separate live syntax path now agree; F-022 fixed. |
| Firewalld rules; Firewalld checks; SSH rule report | Effective runtime/permanent observables and pre/post stops now agree; F-023 fixed. No reload/priority model introduced. |
| Member subnets | Firewall/from/record exclusions agree; VPN remains and no subnet stops. |
| Load guard; Git bash; Stub folder | Explicit test seams, existing locator basis and stopped-daemon fixtures have scheduled producers. |
| Admin check; Outcomes; Probe; Console guard | Outcome totality, publickey-only probe, intentional no-test behavior and bounded console guard remain consistent. |

| All 43 task rows | Result |
|---|---|
| PC; 0 | Human-only commit and dirty-file boundaries preserved; both CLI flags are recorded. No Git write performed. |
| 1 | Three new plan-local checkers, baseline and AC-29/30 selftests explicitly scheduled; peer source wrapper/checker exist. |
| 2; 2a | Constant/test change precedes human live fleet update; no remote update performed. |
| 3 | Testable refactor, per-platform parse/static checks and red/guard exceptions align. |
| 3a; 4 | Existing human A ruling/dependency retained; tag-set second read fixes F-021 without broadening sudo. |
| 5 | Windows policy/report and negative cases remain materially scoped. |
| 6; 6a | Unix listener/target corrections and both platforms' key/password/record order align. |
| 7 | Fingerprint/probe/pin refusal remains before unsafe repin, with AC-31 red/green coverage. |
| 7a; 8; 8a | Both retained CLI flags, existing A ruling, image verification and Probe-1 stop remain consistent. |
| 9; 10; 11 | Accurate docs are required; F-024 affects row 9. Targeted/regression/package gates exist or are scheduled. |
| 12; 13; 14; 15 | Human live gates/import checks, Linux format-only listener read, macOS dependency and BUILD_PLAN absence agree. F-024 concerns the reused drive's stated safety condition. |
| H1-1; H1-2; H1-3; H1-4 | Completion, fresh full evidence/state and justified MEU/API no-ops remain coherent. |
| H1-5; H1-6; H1-6a; H1-6b | Templates/validators exist; handoff/AC coverage and tested-state binding precede independent review. |
| H1-7; H1-7a; H1-7b | Independent execution review, target-bound state and ledger approval retain six execution rounds. |
| H2-1; H2-2; H2-3; H2-3a; H2-3b; H2-3c; H2-4 | Reflection, metrics, no-op bases, explicit known-issues store and final privacy scan remain aligned. |
| H2-5; COMMIT; H2-6 | Author-address check, human commit authority, no push and final status-last rule remain. No trailer finding raised. |

Referenced artifacts were checked for existence before command semantics. The missing helper, three new test files and three new plan-local checkers are explicitly in the create inventories and ordered before their dependent validations; the source peer checker/Pester wrapper and invoked core validators exist. Missing registry/build-plan/worktree/API paths are the explicitly justified absence/no-op surfaces. No materially missing executable was found. Repeated policies have named canonical definitions and agree across the changed references; no new contradictory live spelling remains.

### Commands and durable observations

Commands used read-only Git status/diff, `rtk proxy rg`, numbered file reads, task-contract lint, existing fleet tests, parse-only checks, independent local audit/model scripts, public primary-source reads and the harmless command-search probe. Receipt/scratch writes stayed under `review scratch C:/Temp/zorivest/usb-kit-plan/review-r5/`. The only repository write is this rolling review. The plan bytes and four dirty kit-file bytes are preserved. No live hub/member/SSH host, real credential/key/token file, setup script, installer, USB prepare/import operation, sudo/visudo or workspace Git mutation was used. Existing fleet tests use their own temporary local fixtures, including isolated repositories.

```json
{
  "schema_version": "evidence.v1",
  "id": "R5-CENSUS",
  "phase": "static",
  "command": "rtk proxy python -X utf8 C:/Temp/zorivest/usb-kit-plan/review-r5/audit_census.py",
  "exit_code": 0,
  "result": "pass",
  "observed": "456 values; all 912 independent sweeps match; 3137 hits equal 3137 dispositions, 889 updated and 2248 confirmed-consistent; 279 zero searches mapped; four input/output hashes and 15 live literal rg samples agree."
}
```

```json
{
  "schema_version": "evidence.v1",
  "id": "R5-COMMAND-SEARCH",
  "phase": "targeted",
  "command": "rtk proxy python -X utf8 C:/Temp/zorivest/usb-kit-plan/review-r5/windows-search-probe.py",
  "exit_code": 0,
  "result": "pass",
  "observed": "Harmless drive-local powershell.cmd printed DRIVE_LOCAL_COMMAND_SELECTED under ordinary cmd current-directory search. Static prepare inventory excludes that extra file and has no deletion. No kit entrypoint or elevation executed. This reproduces F-024's command-selection failure, not a passing mitigation."
}
```

```json
{
  "schema_version": "evidence.v1",
  "id": "R5-SOURCE-CONTRACT",
  "phase": "manual",
  "procedure": "Trace the corrected listener, sudo and firewalld call chains against current kit and public upstream source/man pages; run contract_cases.py on inert source objects and written-rule models, and coverage_audit.py over both plan files and their r0 snapshot; attempt each finding's refutations.",
  "observer": "Codex",
  "command": null,
  "exit_code": null,
  "result": "pass",
  "observed": "F-021/F-022/F-023 counterexamples removed; runtime ACCEPT/default and DROP/default refuse; offline default normalizes correctly; desktop first enable stops and active rerun/live format path pass. 43 tasks, 31 AC ids in 33 rows, 22 Named definitions. D-1/D-2 entries/briefs, ruling rows and sudoers rule unchanged. No new kit implementation or live-platform success claimed."
}
```

```json
{
  "schema_version": "evidence.v1",
  "id": "R5-STATIC",
  "phase": "static",
  "procedure": "Run task-contract lint on the target task file; parse both existing kit PowerShell files with Windows PowerShell 5.1 AST; run Git bash -n on existing setup-unix.sh.",
  "observer": "Codex",
  "command": null,
  "exit_code": null,
  "result": "pass",
  "observed": "Each command exited 0. Lint: 43 rows, 41 fully checked, 2 view_file exemptions, dependencies acyclic. Both PowerShell files: zero parse errors under 5.1.26100.9818. setup-unix.sh bash -n: exit 0. New plan tests/helper are absent by design and were not executed."
}
```

```json
{
  "schema_version": "evidence.v1",
  "id": "R5-EXISTING-FLEET",
  "phase": "regression",
  "command": "rtk proxy python -B -m pytest scripts/tests/test_fleet_agent.py scripts/tests/test_fleet_hub.py scripts/tests/test_fleet_bootstrap.py scripts/tests/test_fleet_run.py -q -rfE -p no:cacheprovider --basetemp=C:/Temp/zorivest/usb-kit-plan/review-r5/pytest-temp",
  "exit_code": 0,
  "result": "pass",
  "observed": "590 passed in 832.22s (0:13:52). Existing temporary local fixtures only; this does not execute the uncreated USB AC suite or establish live platform behavior."
}
```

### Checklist Results

| Check | Result | Evidence |
|---|---|---|
| PR-1 | pass | All 43 tasks align with work packages, 31 AC ids, corrected platform branches and doc deliverables. |
| PR-2 | pass | All rows unchecked; implementation handoff absent; four dirty kit files predate this plan and are untouched. |
| PR-3 | pass | Linter verifies 43 rows, required fields and acyclic dependencies. |
| PR-4 | pass | New executable/check/test paths are scheduled before use; source-correct fixtures and live checks now allow ordinary desktop completion. F-024 is an inaccurate deliverable claim, not a missing test executable. |
| PR-5 | fail | F-024: the source does not support the newly claimed differently-trusted-drive refresh mitigation. Other source tags and human A rulings remain accurate. |
| PR-6 | pass | Independently reproduced raw receipt, every disposition, counts, complete source lines, all sweeps, four hashes and 15 live samples. |
| PR-7 | partial | Excluded signing/hash work stays within the coordinator's docs-only direction; its newly asserted prepare fallback is inaccurate (F-024). No new code task demanded. |
| PR-8 | fail | F-024's prepare chain has fixed overwrites but no producer for removing executable extra files; the Windows command-selection counterexample survives. Runtime/permanent target control is fixed. |
| PR-9 | pass | Named policies and changed references agree; no materially contradictory repeated predicate found. |
| DR-1 | fail | New preparation-as-mitigation claim fails against the actual write inventory and launcher; pending work is otherwise correctly represented as pending. |
| DR-2 | pass | Full old/new/variant census reconciles; unsafe UDP exceptions remain removed. |
| DR-3 | pass | Listener function split, target reads and tag comparison propagate to tasks, definitions, ACs and live mode. |
| DR-4 | partial | Round-4 negative cases remove the prior defects; the new documentation's mitigation remains false despite its equally-trusted text check (F-024). No separate predicate-shape demand. |
| DR-5 | pass | Independent audit scripts, public source traces, exact hashes/counts and a benign reproducible counterexample retained; models distinguished from implementation tests. |
| DR-6 | fail | Risks/WP-U7/Out of Scope offer a prepare workaround that current prepare/launcher behavior does not support (F-024). |
| DR-7 | pass | Current counts/hashes reproduced; unrun new ACs and live platforms not reported as passing. |
| DR-8 | pass | D-1/D-2 residuals remain disclosed; code risk remains excluded and this review explicitly withholds approval on its inaccurate mitigation text. |

### Verdict and next action

`changes_required`. Resolve **F-024 before execution** through `/plan-corrections`, within the coordinator's documentation-only direction. Preserve the now-fixed listener resume/live split, distinct firewalld target reads, sudo-tag set comparison, record retention facts and D-1/D-2 A rulings. Round 6 is the last review; if it does not approve, take the plan to the human. This review authorizes no execution, commit or push.

The remaining limitations are source-derived fixtures until execution, unobserved live Ubuntu/Fedora/macOS/Windows behavior, and the code/record trust residuals explicitly described above. No new out-of-contract observation is added; F-024 is the new documentation's factual defect, not an expanded code-integrity requirement.

```json
{
  "schema_version": "review-verdict.v1",
  "date": "2026-11-08",
  "review_mode": "plan",
  "target_plan": "docs/execution/plans/2026-11-07-usb-kit-hardening",
  "agent": "Codex",
  "requested_verbosity": "detailed",
  "verdict": "changes_required",
  "summary": "Round 5 of 6: F-021, F-022 and F-023 are fixed and PR-6 passes. F-024 is High: preparing the same populated drive again leaves extra executable files that the Windows launcher can select, so the proposed workaround for differently trusted members is inaccurate. Correct the documentation before execution; no code fix is required. All 43 rows, 22 definitions and 31 ACs reviewed. D-1/D-2 stay ruled A. Round 6 is last.",
  "findings": [
    {
      "id": "F-024",
      "severity": "High",
      "confidence": "High",
      "finding": "The new guidance presents another prepare into the same drive folder as an alternative to equally trusted members. prepare preserves extra files; a visited member can leave powershell.cmd, which the unchanged Windows launcher can select from that folder before the trusted setup. The claimed mitigation therefore still permits attacker code on the next member. This is a documentation accuracy defect (PR-5/PR-8, DR-1/DR-6), not a new code-authentication requirement.",
      "file_line": "docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:168-171; :884-892; :901; :1041; task.md:56; .agent/fleet/usb/fleet_usb.py:73-83; .agent/fleet/usb/Setup Windows.cmd:6,9",
      "recommendation": "Correct only the documentation: remove preparation of the same populated folder as a sufficient trust reset, or specify an independently clean reconstruction and how records are retained and revalidated. Preserve the code exclusion and the accurate overwrite/preservation facts.",
      "status": "open"
    }
  ],
  "checklist_results": [
    {
      "check": "PR-1",
      "result": "pass",
      "evidence": "All 43 tasks align with work packages, 31 AC ids, corrected platform branches and doc deliverables."
    },
    {
      "check": "PR-2",
      "result": "pass",
      "evidence": "All rows unchecked; implementation handoff absent; four dirty kit files predate this plan and are untouched."
    },
    {
      "check": "PR-3",
      "result": "pass",
      "evidence": "Linter verifies 43 rows, required fields and acyclic dependencies."
    },
    {
      "check": "PR-4",
      "result": "pass",
      "evidence": "New executable/check/test paths are scheduled before use; source-correct fixtures and live checks now allow ordinary desktop completion. F-024 is an inaccurate deliverable claim, not a missing test executable."
    },
    {
      "check": "PR-5",
      "result": "fail",
      "evidence": "F-024: the source does not support the newly claimed differently-trusted-drive refresh mitigation. Other source tags and human A rulings remain accurate."
    },
    {
      "check": "PR-6",
      "result": "pass",
      "evidence": "Independently reproduced raw receipt, every disposition, counts, complete source lines, all sweeps, four hashes and 15 live samples."
    },
    {
      "check": "PR-7",
      "result": "partial",
      "evidence": "Excluded signing/hash work stays within the coordinator's docs-only direction; its newly asserted prepare fallback is inaccurate (F-024). No new code task demanded."
    },
    {
      "check": "PR-8",
      "result": "fail",
      "evidence": "F-024's prepare chain has fixed overwrites but no producer for removing executable extra files; the Windows command-selection counterexample survives. Runtime/permanent target control is fixed."
    },
    {
      "check": "PR-9",
      "result": "pass",
      "evidence": "Named policies and changed references agree; no materially contradictory repeated predicate found."
    },
    {
      "check": "DR-1",
      "result": "fail",
      "evidence": "New preparation-as-mitigation claim fails against the actual write inventory and launcher; pending work is otherwise correctly represented as pending."
    },
    {
      "check": "DR-2",
      "result": "pass",
      "evidence": "Full old/new/variant census reconciles; unsafe UDP exceptions remain removed."
    },
    {
      "check": "DR-3",
      "result": "pass",
      "evidence": "Listener function split, target reads and tag comparison propagate to tasks, definitions, ACs and live mode."
    },
    {
      "check": "DR-4",
      "result": "partial",
      "evidence": "Round-4 negative cases remove the prior defects; the new documentation's mitigation remains false despite its equally-trusted text check (F-024). No separate predicate-shape demand."
    },
    {
      "check": "DR-5",
      "result": "pass",
      "evidence": "Independent audit scripts, public source traces, exact hashes/counts and a benign reproducible counterexample retained; models distinguished from implementation tests."
    },
    {
      "check": "DR-6",
      "result": "fail",
      "evidence": "Risks/WP-U7/Out of Scope offer a prepare workaround that current prepare/launcher behavior does not support (F-024)."
    },
    {
      "check": "DR-7",
      "result": "pass",
      "evidence": "Current counts/hashes reproduced; unrun new ACs and live platforms not reported as passing."
    },
    {
      "check": "DR-8",
      "result": "pass",
      "evidence": "D-1/D-2 residuals remain disclosed; code risk remains excluded and this review explicitly withholds approval on its inaccurate mitigation text."
    }
  ]
}
```

🕐 Completed: 2026-11-08 12:04 (EST)

## Corrections Applied — 2026-11-08, round 5

Applied by the plan's author through `/plan-corrections`. This section is not an approval. All earlier text in this file is unchanged, except the frontmatter `verdict:` value, which `/plan-corrections` sets to `corrections_applied`; `findings_count:` stays 1. Only an independent reviewer can set `approved`.

This pass covers F-024 of round 5. The finding was checked first against the cited plan lines, `fleet_usb.py`, `Setup Windows.cmd` and the Microsoft command-search page. It held, and it is not dismissed. The rule for this pass: documentation only; `equally trusted` stays the main rule; the honest alternative is a drive that only the hub has written, with the record retention stated exactly; and a `prepare` into a folder that already holds files is called what it is, not a reset. Line numbers are for the final files: `plan` is `implementation-plan.md` and `task` is `task.md`.

Direction in this pass:

- **Approach.** The coordinator's brief: correct F-024 in documentation only; keep `equally trusted` as the main rule; give the alternative of an `import` on the hub and then a `prepare` onto a new or freshly formatted drive, with the retention facts; state that a `prepare` into a populated folder is not a reset, and cite the Microsoft page; update the AC-21 text check; add no code task, launcher patch, purge step, signing or hash list; keep the Out of Scope row honest that code authentication is excluded.
- **D-1 and D-2 stay ruled A.** As relayed ("recoomendations for D-1 D-2 accepted", 2026-11-08). The D-1 and D-2 Decision Log entries, both Decision Briefs (plan:1337-1383, :1385-1406), the sudoers rule line (plan:206) and rows 3a and 7a (task:47, :53) are byte-identical to the text before this pass (`12-d1-d2.txt`). F-024 touches none of them.
- **Review rounds.** The plan loop stays at 6 rounds (plan:89-90). This is the round-5 correction pass; one review round remains.

| Item | Disposition | Correction | Where | Evidence |
|---|---|---|---|---|
| F-024 | fixed | The Risks bullet and the WP-U7 drive text keep `equally trusted` as the rule and no longer offer another `prepare` as the alternative. For a member that is not equally trusted, the human runs `import` on the hub for the records collected so far, then runs `prepare` onto a new drive, or onto one freshly formatted on the hub, so that only the hub has written it. WP-U7 states the retention facts: `import` reads only `members/*.json`, writes the entry of each name that it takes, keeps every other name in the hub's `fleet_members.json` and writes `fleet_config` and `fleet_known_hosts` from that whole file, so a format after an `import` loses no record that it took. It takes each valid record, also one whose member does not answer, except one that the pin refusal refuses. A record that it skips or refuses, and a record written after the last `import`, exist only on the old drive: a format loses them, and that member runs its setup again from a drive that the hub wrote; until then the old drive stays away from every member. On a new drive, the name-clash stop of Record retire sees no earlier member's record, but the pin refusal still applies. Both places state that a `prepare` into a folder that already holds files is not a reset: it rewrites the kit's own files and keeps the records and every other file. WP-U7 adds that `Setup Windows.cmd` calls `net` and `powershell` by bare name and that `cmd.exe` searches the current directory before `PATH` unless `NoDefaultCurrentDirectoryInExePath` is set, so a `powershell.cmd` that a visited member left in the drive folder can run in place of Windows PowerShell, before the trusted setup, and raise the elevation prompt for its own code. AC-21 also fails a `usb/README.md` without the words `not a reset`, and its source cell adds review F-024, `fleet_usb.py:66-89,176-203`, `Setup Windows.cmd:4-9` and the Microsoft page. Row 9 and the Files table name the hub-written drive and the not-a-reset note. The Out of Scope row now says that the kit does not authenticate the code on the drive, names the hub-written drive in place of a fresh `prepare`, and says that a `prepare` into a used folder keeps a planted file. A new reference names the Microsoft page. No code task, launcher patch, purge step, signing or hash list was added. | plan:168-174 (Risks), :887-909 (WP-U7), :918 (AC-21), :927 (Files), :1058 (Out of Scope), :1440 (reference); task:56 (row 9) | `fleet_usb.py:66-89`: `prepare` writes each of `MEMBER_FILES` (`:75-81`) and `hub.pub` (`:83`), makes `members/` only if it is missing (`:74`), and deletes nothing. `import_records` (`:176-215`) reads only `members/*.json` (`:177`), skips an invalid record (`:188-192`), stores each valid record, also an unreachable one (`:194-200`), and keeps every other name (`:183-203`). `Setup Windows.cmd:4` runs `net session`, and `:6` and `:9` run bare `powershell`. The Microsoft `NeedCurrentDirectoryForExePathA` page: `cmd.exe` uses `.;%PATH%` when the function returns TRUE, and the function checks only that `NoDefaultCurrentDirectoryInExePath` exists, not its value (`02-ms-line835.txt`, `26-ms-line833.txt`, `fetched/`). The reviewer's benign `powershell.cmd` probe (review:1626). |

The round-4 Residual-risks statement at review:1583, "An extra file planted on the drive survives `prepare`, but no launcher runs it.", was inaccurate, because `Setup Windows.cmd` can run a planted `powershell.cmd` (F-024); the round-4 Observation row's "otherwise `fleet_usb.py prepare` runs again" (review:1535) is superseded by this pass, and both earlier texts stay unchanged.

**Blast-radius census:** 52 round-5 values declared, 504 values swept in all, 3697 sites found, 191 updated, 3506 confirmed consistent.

The 504 values are 170 old, 245 new and 89 variants. 450 carry from rounds 1 to 4: the 448 round-4 sweeps and the 8 values that round 4 derived from its diff, less the 6 that round 5 declares again. 52 are the round-5 values (11 old, 22 new, 19 variants); 6 of the variants (among them `prepare`, `equally trusted` and `one-drive trust rule`) were already carried, so each is swept once. 2 come from the code spans that a script derived from the round-5 diff (`:188-192` and `:194-200`, `derived-values.txt`). The 271 values that round 3 derived from its own diff are not derived again. 2 carried values moved to old, because round 5 removed their only hits: `` prepare` again `` and `` prepare` runs again ``, each with 0 final hits and 1 r0 hit. The round-5 old values are the old alternative (`` otherwise `fleet_usb.py prepare` runs again ``, `on the hub before each member`, `` otherwise run `prepare` again ``, `` a fresh `prepare` before each member ``), the old retention wording (`` leaves the records in `members/` and any other file as they are ``, `so the fingerprint compare still applies`), the old AC-21 check and source (`` without the words `equally trusted`, or without ``, `scope addition, 2026-11-08); Local Canon`) and the old Files and Out of Scope wording. Each value is searched in two texts: `final`, and `r0`, the text before this pass (the round-4 output, whose hashes the round-5 recheck reproduced). The script ran 1008 searches.

| Class | Target | Searches | Hits | Updated | Confirmed consistent | Zero-hit |
|---|---|---|---|---|---|---|
| old | final | 170 | 65 | 0 | 65 | 141 |
| old | r0 | 170 | 80 | 15 | 65 | 129 |
| new | final | 245 | 932 | 67 | 865 | 1 |
| new | r0 | 245 | 890 | 25 | 865 | 25 |
| variant | final | 89 | 889 | 66 | 823 | 3 |
| variant | r0 | 89 | 841 | 18 | 823 | 5 |
| **Total** | | **1008** | **3697** | **191** | **3506** | **304** |

- Disposition is set against the paired line in the other text. `updated` means the paired line differs, so round 5 changed the line, or the line has no pair. `confirmed-consistent` means the paired line is the same and the line was read against the corrected text. The verifier checks the pairing for the 3621 hits that have a paired line.
- The 65 old-value hits in the final text each have a reason in the map's last column. Unresolved: 0. All 65 are on lines that round 5 did not change. 64 keep their earlier reasons. The 65th is new: `scope addition, 2026-11-08); Local Canon` at plan:796, the AC-31 source cell, which F-024 did not touch; only the AC-21 source cell now names review F-024 before `Local Canon`.
- 10 of the 11 round-5 old values have zero final hits; the 11th is the AC-31 source cell above.
- The zero-hit new value is `host key changed`, carried from round 3; the plan says `changed key`. The three zero-hit variants are `default if` and `Default if`, also carried, and the round-5 variant `before each member` (2 r0 hits), which shows that the phrase is gone. Each round-5 new value and every other variant is found in the final text.
- The read list holds 193 distinct final lines: 26 changed in round 5, and 167 unchanged lines that a round-5 value hits. This pass read all 193.

Receipts (`receipts in C:/Temp/zorivest/usb-kit-plan/corrections-r5/`):

- `census-receipt.txt`: every search, its exit code and each matching line in full.
- `disposition-map.txt`: one row per receipt hit, with the zero-hit rows; each row names its paired line in the other text.
- `census-summary.txt`, `derived-values.txt`, `read-list-r5.txt`, `census-verify.txt` and `final-hashes.txt`.
- `r0/` (the text before this pass) and `r0-hashes.txt`.
- `fetched/`: the Microsoft `NeedCurrentDirectoryForExePathA` page; `02-ms-line835.txt` and `26-ms-line833.txt` hold the cited lines.
- The numbered receipts from `01-`: the fetch, the edit dry run and the applies (`06-dry.txt`, `07-apply.txt`, `11-apply-b.txt`, and `27-review-dry.txt` and `28-review-apply.txt` for this section), the diffs (`13-plan-diff.txt`, `17-task-diff.txt`), the census runs, `12-d1-d2.txt` and `24-ac-count.txt`; and `lint-final.txt` and `privacy-final.txt`.
- `tools/`: the edit blocks of this pass, `apply_edits.py`, and the census, verify and D-1/D-2 check scripts.

**Verification:** `census_verify_r4.py` passes on the round-5 output (`census-verify.txt`: sweeps 504, searches 1008, receipt hits 3697, map rows 3697, zero-hit 304, paired-line checks 3621). It is the round-4 verifier, unchanged; the plan folder and the receipts folder are its arguments. It checks each hit against the whole file line, each search's exit code against its hits, an explicit zero-hit line, the receipt-to-map match, the dispositions, that no reason says UNRESOLVED, the four hash rows, the pairing, and one final and one r0 search per sweep. The census script `census_r5.py` is the round-4 script with the round-5 values, reasons and paths (`make_census_r5.py`). `lint_task_contract.py` passes with 43 rows (`lint-final.txt`). The plan still has 31 ACs in 33 AC rows (AC-14 and AC-27 have two halves) and `AC_COUNT` 31 (`24-ac-count.txt`). The privacy scan of both plan files and this file, with the extra terms given only on the command line, finds 0 hits (`privacy-final.txt`). No AC was executed, because every correction is plan text and the tests do not exist yet.

Deviations from the reviewer's suggested shape:

- The reviewer offered two options; this pass keeps both. `equally trusted` stays the rule, with its residual disclosed, and the hub-written drive is the stated alternative for a member that is not equally trusted.
- The text names `net` with `powershell`, because `Setup Windows.cmd:4` also calls `net session` by bare name, before either `powershell` call.
- The retention text was checked against `import_records`, and it states two facts more: a format loses a record that `import` skipped or refused or that was written after the last `import`, and on a new drive the name-clash stop sees no earlier record while the pin refusal still applies.
- AC-21 now requires the words `not a reset` as well as `equally trusted`.
- Documentation only, as directed: no purge step, launcher patch, signing, hash list or `NoDefaultCurrentDirectoryInExePath` prerequisite.

Residual risks:

- The kit still does not authenticate the code on the drive. A member that is equally trusted but compromised can change that code for the next member; documentation cannot detect it.
- The current-directory search comes from the Microsoft page and the reviewer's benign probe, not from a run of the kit's launcher on a Windows member.
- A format on the hub rewrites the file system, not the drive's firmware; a drive that a member could reprogram is not addressed.
- Rows 12 to 14 (task:59-61) run `prepare` on the drive folder before each live check on the human's own members; they rely on those members being equally trusted, and they are unchanged.
- A format loses a record that `import` skipped or refused, or one written after the last `import`; that member then runs its setup again.
- 6 plan rounds share the unchanged 10,500,000-token budget.

**Open human decisions:** none. D-1 and D-2 stay ruled A, as relayed. This pass adds no new human decision.

Corrected input SHA-256 values (`implementation-plan.md` has 1464 lines, 18 more than before this pass; `task.md` has 108 lines and 43 rows):

- `implementation-plan.md`: `5b27773e80459f40df2b0a49714f4b1d7946bb360fe0102d8e8a464287153dcd`
- `task.md`: `a019e64eb42b696f39c977a0d60d5da369dcb98e2e982d3c7795e126391f0918`

Not resolved:

- No Windows member ran the launcher with a planted `powershell.cmd`; the path comes from the Microsoft page and the reviewer's benign probe, and row 12 is the first real Windows check of the kit.
- No independent census audit ran in this pass; the verifier above is the author's, from round 4. The next reviewer can repeat the sweeps from `census-receipt.txt` and `r0/`.
- The current `usb/README.md` and `install-usb/README.md` belong to another session's uncommitted work and were not edited. The hub-written drive and not-a-reset text exists only as WP-U7 work for row 9.

🕐 Completed: 2026-11-08 12:26 (EST)

## Recheck (2026-11-08) — Round 6 of 6

Executing this plan should close the seven kit gaps, preserve a usable SSH admin path on Windows, macOS and Linux, implement the approved record safeguards, and state the writable-drive limits honestly. The corrected plan supports that objective: F-024 is fixed, and no blocking defect remains.

**Verdict: `approved`, with two Low correction notes below.** This is round 6 of 6, the last round authorized by the human's 2026-11-08 instruction, "Add 3 more rounds". No further review round is presumed. D-1 and D-2 remain ruled A. The human's reading at the plan-to-execution gate remains the terminating trust anchor.

### Findings and nonblocking correction notes

**No finding must be fixed before execution starts.** F-001 through F-023 remain resolved; F-024 is fixed as explained below. The following are correction notes under the workflow's Materiality Gate, not grounds to withhold approval. Per the approved-verdict contract, they are recorded in prose and the structured summary; the structured findings array and frontmatter findings count are zero.

Here `plan` means `docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md`, and `task` means the adjacent `task.md`.

| ID | Severity | Confidence | Blocking | Supported issue, failure and refutation | File:line | Recommendation |
|---|---|---|---|---|---|---|
| F-025 | Low | High | no | A-8's reasoning says that `--no-test` means no connection to the member. The current import calls `reachable` unconditionally, which opens TCP sockets, and only gates the later SSH/admin test on `test`. Thus the wording can mislead someone expecting an offline import. Refutation: A-8's chosen behavior and AC-18 correctly say to skip the admin check/probe and make no SSH call; neither requires removing reachability checks. The intended correction is readily inferable and changes no approved behavior. | `plan:1230`, `:774`, `:795`; `.agent/fleet/usb/fleet_usb.py:123-130`, `:194`, `:211`, `:225-229` | Say "no SSH/admin/probe test" rather than "no connection"; preserve the TCP reachability behavior. |
| F-026 | Low | High | no | AC-21 explicitly names the words `equally trusted` and `not a reset`, but does not name a negative copy missing the new reconstruction/retention instructions. A scratch model of only its enumerated USB-README conditions passes both a copy with the hub-only reconstruction/retention recipe removed and one with the skipped/refused/unimported-record loss warning removed. Removing either checked phrase fails the same model. Refutation: the positive AC still says "The text checks above pass", and WP-U7 and row 9 explicitly require the complete guidance. The new test file does not exist yet. This proves the enumerated negatives alone are insufficient, not that the future test cannot reject omissions or that the deliverable is absent from the plan. It is a test-contract clarification under Materiality Gate 3, not a demonstrated false-passing implemented gate. | `plan:893-905`, `:918`, `:927`; `task:56` | Make the intended text checks explicit: include negative copies missing the ordered import/new-or-formatted-drive/prepare guidance and the retention/loss warning. Keep the full WP-U7 guidance as the deliverable; phrase presence alone is insufficient. |

These notes do not reopen F-024 or demand a code-authentication control. No launcher patch, purge step, signing scheme or hash list is requested. No other supported finding survived the source and contract checks.

### F-024 — fixed against the corrected plan and current source

"Fixed" means the plan removes the counterexample; implementation and the new tests remain unstarted.

| Surface | Result and evidence |
|---|---|
| Risks | `plan:168-174` keeps equally trusted members as the rule, substitutes import followed by a new or hub-formatted drive, and expressly says a populated-folder prepare is not a reset. |
| WP-U7 | `plan:887-909` gives the hub-written-drive path, retention/loss cases, unchanged pin refusal, fixed overwrite inventory and conditional command-search explanation. It no longer offers prepare into the old populated folder as the differently-trusted-member remedy. |
| AC-21 | `plan:918` adds the not-a-reset deletion case and the source references. Its two named phrase-deletion cases are real negatives; F-026 records the limit of treating those phrases as the entire check. |
| Files and task | `plan:927` and `task:56` expressly name the hub-written drive and not-a-reset note. |
| Out of Scope | `plan:1058` says the kit does not authenticate drive code, names the hub-written alternative, and acknowledges that prepare into a used folder preserves a planted file. This stays within the coordinator's documentation-only scope. |
| New Reference | `plan:1440` cites the actual Microsoft command-search page. Its conditional interpretation is supported below. |
| Other prepare mentions | All 16 final literal hits were re-swept. `task:59-61` refresh this plan's scripts for live checks on the human's members, under the equally-trusted rule; they make no claim to reset a contaminated drive. Characterization, line-end, MEMBER_FILES, folder-definition and state references describe prepare's actual role. No current plan occurrence retains the old differently-trusted-member fallback. Historical review/correction passages remain history, with their supersession recorded. |

The source chain is `fleet_usb.py main:227-229` to `prepare:66-89`: create the folder and `members/` if needed (`:73-74`), overwrite each fixed `MEMBER_FILES` item (`:75-81`), and write `hub.pub` (`:82-83`). There is no deletion of arbitrary extra files. The helper is not in today's inventory; WP-U3 and `task:48` explicitly add it before WP-U7 is delivered. The corrected description accounts for that planned change rather than claiming it already exists.

A new or freshly formatted filesystem removes the planted ordinary file from the next member's drive contents; writing the kit from the hub supplies the intended reconstruction producer. Merely renaming the old prepare operation would not have done that. The correction now prescribes a different operation on a different/empty filesystem, with losses stated.

### Record retention — what survives, what is lost

The inspected implementation is `fleet_usb.py read_record:92-120` and `import_records:176-215`. The following distinguishes today's code from WP-U5b's scheduled pin refusal.

| Case | Current code and planned result |
|---|---|
| Valid record taken by import | The name's connection entry is assigned at `:198-200`, and the complete members dictionary is written to `fleet_members.json`, rendered into `fleet_config`, and used for `fleet_known_hosts` at `:201-203`. Other names remain from the loaded dictionary (`:183-184`). Formatting the drive afterward does not erase those hub entries. |
| Member does not answer | `reachable` can return None; import nevertheless assigns the entry using the first record address (`:194`, `:198-200`), writes state before reporting the failure (`:201-209`), and exits nonzero. Thus nonzero does not mean no record was saved. The new WP-U7 explicitly includes this case (`plan:898`). Reachability or successful setup is not thereby proved. |
| Unreadable/invalid record | `:188-192` skips it before assignment. The skipped input is not newly saved; an older same-name hub entry, if any, remains. Formatting destroys that drive copy, not the older hub entry. `plan:899-901` warns of the loss and gives a setup-again route. |
| Changed key refused by WP-U5b | Today's code warns and overwrites (`:195-199`); the plan expressly replaces this at `plan:776-782`, `:796` and `task:52`. Under that planned refusal, the old pinned entry/block/line stay and the rejected replacement is not saved. The drive copy of the rejected replacement is lost on format. WP-U7's exception and its statement that the hub pin still applies on a new drive are correct (`:899`, `:902-903`). Setup again alone does not authorize a changed key; WP-U5b's fingerprint-at-screen and Undo steps still apply. |
| Record written after the last import | Its new contents have never reached the hub. A format loses them; an older imported version can still exist on the hub. WP-U7 warns of this and says to rerun setup from a hub-written drive (`plan:900-902`). |
| Records absent from the new drive | Prepare creates an empty members folder; it does not copy the hub dictionary back to the drive. This does not delete hub entries. The drive's name-clash guard has no old record to compare, but import's hub pin refusal remains in force (`plan:902-903`). |
| Retained entry versus original JSON | Import retains the normalized connection fields, including one chosen/fallback address, not a byte-for-byte archive of the original record: `read_record:120`, `import_records:198-203`. Alternate addresses and the source JSON's `changed`/`created` metadata are not archived. WP-U7 describes the entry and the three hub files; its retention claim is about that imported connection record, not an archive of all drive bytes. Keep the old drive for another import when those unsaved contents are still needed, as `plan:901-902` says. |

An import that aborts before the writes, for example because the hub key/state is unusable, has not "taken" records under this description. Neither the code nor the revised text promises preservation merely because a command was started.

### Windows command search — before and after elevation

`Setup Windows.cmd:4` calls bare `net session`; `:6` calls bare `powershell` for a `Start-Process -Verb RunAs` relaunch of the absolute launcher path; `:9` calls bare `powershell` for the script using the absolute drive-derived script path. The launcher never changes to its own directory. An absolute script argument does not make the interpreter name absolute.

[Microsoft's command-search documentation](https://learn.microsoft.com/en-us/windows/win32/api/processenv/nf-processenv-needcurrentdirectoryforexepatha) says cmd chooses either a search including the current directory or PATH alone; the presence of `NoDefaultCurrentDirectoryInExePath` controls that choice, regardless of its value. [Start-Process](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.management/start-process?view=powershell-5.1) exposes a working-directory setting and the RunAs verb. The kit sets no explicit working directory. This review does not assume that the elevated command interpreter's current directory equals the drive folder.

| Invocation stage | What a drive-local planted file can replace |
|---|---|
| Unelevated, current directory is the drive folder, ordinary current-directory search | A planted `net.cmd` can replace `net` at line 4, before the branch. If the branch reaches line 6, a planted `powershell.cmd` can replace that unelevated elevation-request interpreter. Its own code can request elevation; no later drive-current-directory assumption is needed. A planted net command returning success can also steer the existing process to line 9 without legitimate elevation. |
| Already elevated, current directory is the drive folder | The bare line-4 command and, if reached, line-9 interpreter are subject to the same current-directory selection. |
| Genuine RunAs relaunch with another current directory | A planted file left only in the drive folder is not selected merely because the batch/script file is there. Selection for line 4 or 9 depends on the new current directory and PATH. It is incorrect to promise that line 9 necessarily runs the planted drive file after UAC. |
| Another current directory from the start, or current-directory search disabled | The drive-local example does not apply merely from the launcher's location. PATH can still contain unsafe entries, but that is not claimed to be prepare's behavior. |

The corrected `plan:906-909` is conditional on the drive folder actually being the current directory, and says "can", so it neither guarantees post-elevation selection nor overlooks the pre-elevation attack. The shorter risk/reference sentences (`:174`, `:1440`) state a possible execution route and point to WP-U7; they do not assert every invocation has that directory.

A harmless new scratch probe ran only marker-printing `net.cmd` and `powershell.cmd` fixtures. With the fixture drive as current directory, both drive markers were selected. With a different current directory and the same synthetic PATH, both PATH markers were selected. All four exited 0. No kit launcher, setup, actual net.exe, PowerShell interpreter, elevation prompt or remote connection was run for this probe.

### PR-6 — independent census gate

**Pass.** The independent reviewer script imports none of the planner's census/verifier code. It parses the complete raw receipt and per-hit map referenced by the round-5 corrections log, joins by search/target/location, checks every full source line, re-sweeps all literals against both final and r0 texts, checks the dispositions against paired lines, and reproduces the totals. It also repeats 15 samples through live unfiltered `rtk proxy rg`, including zero-hit old alternatives and the new trust/reset/format/search terms.

| Check | Independently reproduced |
|---|---|
| Declared unique values | 504: 170 old, 245 new, 89 variants |
| Searches | 1008, one final and one r0 search per value |
| Hits/map dispositions | 3697 = 191 updated + 3506 confirmed-consistent; no unmatched, undispositioned or clipped hit |
| Empty searches | 304, each with its explicit zero-hit map row and matching exit code |
| Paired-line checks | 3621; source location and disposition agree; unpaired hits are updated |
| Class/store hits | old/final 65; old/r0 80; new/final 932; new/r0 890; variant/final 889; variant/r0 841 |
| Live rg samples | All 15 match the raw receipt |
| Final plan SHA-256 | `5b27773e80459f40df2b0a49714f4b1d7946bb360fe0102d8e8a464287153dcd` |
| Final task SHA-256 | `a019e64eb42b696f39c977a0d60d5da369dcb98e2e982d3c7795e126391f0918` |
| r0 plan SHA-256 | `58992688a800af1ab824a829b5963282283ce97b8f4c6482989ec991c50564c5` |
| r0 task SHA-256 | `6219e3eb010b809246d2272bf2356f3ebdbd0ca39241d9b590f5f475f82fb6a6` |

These agree with the correction log, summary, raw receipt, map and hash receipts. The r0 hashes also match the preceding round's reviewed outputs. The planner's `census-verify.txt` was not used as proof; its assertions were checked independently. The declared historical snapshot is not treated as an author-forgery threat.

Reviewer scripts and receipts are in `review receipts in C:/Temp/zorivest/usb-kit-plan/review-r6/`: `audit_census.py`/`census-audit.txt`, `source_audit.py`/`source-audit.txt`, `live_samples_and_doc_checks.py`/`live-samples-and-doc-checks.txt`, `drive-mentions.txt`, `task-lint.txt`, `existing-static-tests.txt`, `dirty-files-hashes.txt` and `stamp.txt`. The command-selection fixtures are under that same scratch directory.

### Usability, complexity and decisions

The hub runs Windows/PowerShell (`plan:1458`; `install-usb/README.md:6`). The existing USB README supplies both runnable Python commands: `python .agent/fleet/usb/fleet_usb.py import E:\fleet-usb` at `:75-77` and `python .agent/fleet/usb/fleet_usb.py prepare E:\fleet-usb` at `:15-17`. Its exFAT prerequisite is at `:8`. WP-U7 now orders those operations around a new or freshly formatted drive, rather than implying prepare performs a format. The installer README's storage-reuse section (`:129-138`) supplies the Windows administrative disk/partition/exFAT commands if an installer drive is being reclaimed. No Unix-only formatting command is imposed on the hub. A human must select the actual drive, as with the existing E: example; a new drive may need exFAT formatting before prepare. No command or OS mismatch was found that prevents the stated path.

The review did not format or prepare a drive. Usability is a source/command judgment, not a live drive result. An unreachable member can produce import exit 1 after saving its entry; skipped/refused records and records not yet imported need the explicit treatment above. Those cases do not silently become successful live-check evidence: `task:59-61` require the import to pass and the member to be on. The new-drive path leaves pins in the hub, so a changed-name/key collision remains an intentional human stop, not a reset workaround.

The normal Ubuntu first-enable stop/resume, runtime/permanent firewalld rules, macOS Remote Login steps and Windows physical-network preflight remain as reviewed in round 5. The new filesystem instruction adds no parser, privilege boundary or launcher change. No concrete complexity failure was found; no preference-only simplification is requested.

D-1/D-2 log entries, both full briefs and task rows 3a/7a are byte-identical to r0. Their A rulings, fixed helper verbs/environment, repository-package root residual and installer-before-binary-verification timing remain as briefed (`plan:1131-1150`, `:1337-1404`). No option is re-decided. There is no new open human design decision.

### Complete coverage and verification

All 43 task rows, all 22 Named definitions, all 31 AC ids (33 table rows, including both halves of AC-14 and AC-27), all decisions, stop conditions, exclusions and all seven round-5 changed regions were read and cross-checked. The command-artifact inventory found each executable/test/schema either present or explicitly scheduled before use; external source URL suffixes were excluded from repository-path false positives.

| Scope | Coverage and result |
|---|---|
| WP-U1; AC-1/2/3; rows 2/2a | Constant consumers/producer, expected-set update, hub-first update and human hello gate align. Existing unchanged-set guard passes on the current, still-unmodified code. |
| WP-U2; AC-4/5/6/7/12/28; row 3 | Loading seams, bash/PowerShell constraints, line ends, Git-root layouts and green characterization exceptions remain explicit. New files are scheduled, not claimed implemented. |
| WP-U3; AC-8/9/10/11/26; rows 3a/4 | Helper paths/modes/parent walk, fixed argv, clean environments, sudo parser/second read/probe, tag-set comparison and outcomes remain inside D-1 A. |
| WP-U4; AC-13; row 5 | Physical-network policy, active-store rules/profiles, report chain and shared encoded extraction remain aligned. No new demonstrable bypass/dead end. |
| WP-U5; AC-14 Unix/15/16/27 Unix; row 6 | Listener enable-only guard and format-only live parser remain distinct; offline/running zone paths and both targets, key-auth order, rollback and record retirement remain intact. |
| WP-U5w; AC-14 Windows/17/27 Windows; row 6a | Guard/preflight/retirement precede changes; keys and checks precede password-off; restart/restore/fingerprint sequence remains explicit. |
| WP-U5b; AC-18/31; row 7 | Probe/admin checks, pin refusal and per-record unchanged-old-state tests remain. F-025 concerns only the no-connection wording. |
| WP-U6; AC-19/20; rows 7a/8/8a | Image signature/exit/status/hash checks precede disk erasure; CLI conditional ownership, Probe-1 and D-2 A remain as approved. |
| WP-U7; AC-21; row 9 | Entire new documentation read as new text. F-024 fixed; explicit-negative coverage note F-026 recorded without claiming an unimplemented test passed. |
| WP-U8; AC-22/23/24/25/29/30; rows 1/10-15 | Checkers, package inventory/baseline, live selftests and member checks, privacy and byte-bound state remain coherent. No absent unscheduled gate executable was found. |
| PC/0; H1-1 through H1-7b; H2-1 through H2-6; COMMIT | Dirty-file human ownership, full evidence identity, independent-review barrier, target-bound approval, issue registry paths/rendering, reflection/privacy closeout and no-commit/no-push gates align. All rows remain unchecked. |

Commands actually executed included read-only `rtk git status --short`, source/plan reads and `rtk proxy rg`; the three reviewer scratch scripts named above; the task linter; and seven existing static tests selected from `test_fleet_bootstrap.py` and `test_fleet_agent.py`. The linter passes with 43 rows and acyclic dependencies. The selected tests pass, **7 passed in 0.40s**; they cover bootstrap text shape/deletion mutations/update requirements and the unchanged forbidden-command set.

The selected test run used `python -X utf8 -B -m pytest`, `-p no:cacheprovider` and a basetemp under the allowed review scratch directory. No hub/member fixture or fleet command was invoked. No new kit AC, full regression suite, Pester suite or live member test ran this round. Those are execution work, not inferred passes from this review.

Post-write verification (`verify_review.py` and `review-validation.txt` in the same review scratch directory) validates the structured verdict against the cited v1 schema, checks all 17 checklist results, and reconstructs the exact prior review hash from the preserved prefix by reverting only the two frontmatter values. Both plan hashes and all four separately owned dirty-file hashes remain unchanged.

### Checklist results

| Check | Result | Evidence |
|---|---|---|
| PR-1 | pass | All 43 rows align with work packages, 22 definitions and 31 AC ids; row 9 includes the corrected drive guidance. |
| PR-2 | pass | All 43 task statuses remain unchecked; implementation handoff is absent; four dirty kit files are separately owned work. |
| PR-3 | pass | Task linter passes: 43 rows, required fields, receipt/exit discipline and acyclic dependencies. |
| PR-4 | pass | Invoked artifacts exist or have explicit creation tasks before use. F-026 is a nonblocking clarification of AC-21 negative coverage. |
| PR-5 | pass | F-024 replacement agrees with prepare/import source and Microsoft command-search documentation. D-1/D-2 stay A. |
| PR-6 | pass | Independent audit: 504 values, 1008 searches, 3697 hits, 191 updated, 3506 consistent, 304 empty searches, 3621 paired hits; four hashes and 15 live rg samples agree. |
| PR-7 | pass | Every exclusion retains its stated source basis; code authentication remains expressly excluded by the documentation-only direction. |
| PR-8 | pass | No missing producer or dead-end control demonstrated. Reconstruction uses a new/formatted drive; pin refusal and named runtime controls remain scheduled. |
| PR-9 | pass | Complete literal census reconciles; named policies govern repeated references without a material behavioral contradiction. |
| DR-1 | pass | Corrected plan describes pending documentation work; source supports the overwrite and retained-entry claims. F-025 is a nonblocking wording correction. |
| DR-2 | pass | All old prepare-as-reset alternatives are removed from current plan files; historical review text is preserved. |
| DR-3 | pass | Risks, WP-U7, AC-21, Files, Out of Scope, row 9 and the new Reference agree. |
| DR-4 | pass | Explicit word-removal cases fail the modeled checks; whole-guidance omissions expose the recorded Low F-026 coverage note, not a demonstrated implementation gate failure. |
| DR-5 | pass | Independent scripts and exact receipts are retained; harmless command-selection fixtures ran without kit execution or elevation. |
| DR-6 | pass | Current code, planned pin refusal and public Microsoft documentation support the corrected guidance; elevated working-directory behavior is conditional. |
| DR-7 | pass | Four plan hashes and census counts reproduced; task linter and seven existing static tests pass; no new or live AC is claimed executed. |
| DR-8 | pass | Plan approval only; unsigned writable code, accepted option-A limits, firmware limits and required human execution gates remain disclosed. |

All required checklist outcomes are pass. The two Low notes remain visible above; neither is concealed as a blocking failure or claimed resolved. No out-of-contract observation is promoted into scope.

### Verdict and residual risk

**Approved for the plan-to-execution gate.** No supported High/Critical finding remains and the PR-6 procedural gate passes. F-025 and F-026 are nonblocking correction notes under the workflow's Materiality Gate. The human still owns the proceed instruction, row 0 and live member authorization; approval does not start execution or authorize a commit/push.

The kit still does not authenticate writable-drive code. Equally trusted members can be compromised; a hub-written filesystem does not establish firmware integrity; a first import still depends on the human's fingerprint comparison. D-1's configured-package root residual, full Windows admin, D-2's installer-before-verification exposure, customized-policy stops and the need for real platform observations remain disclosed. This is approval of an unstarted plan, not certification of an implemented kit.

Only this rolling review file was changed in the repository; earlier text is preserved apart from frontmatter verdict/findings_count. The four dirty kit files remain untouched. The workflow stops here.

### Structured verdict

```json
{
  "schema_version": "review-verdict.v1",
  "date": "2026-11-08",
  "review_mode": "plan",
  "target_plan": "docs/execution/plans/2026-11-07-usb-kit-hardening",
  "agent": "Codex",
  "requested_verbosity": "detailed",
  "verdict": "approved",
  "summary": "Round 6 of 6: F-024 fixed; no blocking findings. Two Low correction notes: F-025, --no-test still makes TCP reachability connections; F-026, AC-21's explicit word checks alone do not cover omission of the reconstruction and retention guidance, although its positive contract and row 9 require that guidance. Independent census, task lint and seven existing static tests pass. Review recorded in .agent/context/handoffs/2026-11-07-usb-kit-hardening-plan-critical-review.md. Execution remains subject to the human's proceed instruction and row-0 gate.",
  "findings": [],
  "checklist_results": [
    {
      "check": "PR-1",
      "result": "pass",
      "evidence": "All 43 rows align with work packages, 22 definitions and 31 AC ids; row 9 includes the corrected drive guidance."
    },
    {
      "check": "PR-2",
      "result": "pass",
      "evidence": "All 43 task statuses remain unchecked; implementation handoff is absent; four dirty kit files are separately owned work."
    },
    {
      "check": "PR-3",
      "result": "pass",
      "evidence": "Task linter passes: 43 rows, required fields, receipt/exit discipline and acyclic dependencies."
    },
    {
      "check": "PR-4",
      "result": "pass",
      "evidence": "Invoked artifacts exist or have explicit creation tasks before use. F-026 is a nonblocking clarification of AC-21 negative coverage."
    },
    {
      "check": "PR-5",
      "result": "pass",
      "evidence": "F-024 replacement agrees with prepare/import source and Microsoft command-search documentation. D-1/D-2 stay A."
    },
    {
      "check": "PR-6",
      "result": "pass",
      "evidence": "Independent audit: 504 values, 1008 searches, 3697 hits, 191 updated, 3506 consistent, 304 empty searches, 3621 paired hits; four hashes and 15 live rg samples agree."
    },
    {
      "check": "PR-7",
      "result": "pass",
      "evidence": "Every exclusion retains its stated source basis; code authentication remains expressly excluded by the documentation-only direction."
    },
    {
      "check": "PR-8",
      "result": "pass",
      "evidence": "No missing producer or dead-end control demonstrated. Reconstruction uses a new/formatted drive; pin refusal and named runtime controls remain scheduled."
    },
    {
      "check": "PR-9",
      "result": "pass",
      "evidence": "Complete literal census reconciles; named policies govern repeated references without a material behavioral contradiction."
    },
    {
      "check": "DR-1",
      "result": "pass",
      "evidence": "Corrected plan describes pending documentation work; source supports the overwrite and retained-entry claims. F-025 is a nonblocking wording correction."
    },
    {
      "check": "DR-2",
      "result": "pass",
      "evidence": "All old prepare-as-reset alternatives are removed from current plan files; historical review text is preserved."
    },
    {
      "check": "DR-3",
      "result": "pass",
      "evidence": "Risks, WP-U7, AC-21, Files, Out of Scope, row 9 and the new Reference agree."
    },
    {
      "check": "DR-4",
      "result": "pass",
      "evidence": "Explicit word-removal cases fail the modeled checks; whole-guidance omissions expose the recorded Low F-026 coverage note, not a demonstrated implementation gate failure."
    },
    {
      "check": "DR-5",
      "result": "pass",
      "evidence": "Independent scripts and exact receipts are retained; harmless command-selection fixtures ran without kit execution or elevation."
    },
    {
      "check": "DR-6",
      "result": "pass",
      "evidence": "Current code, planned pin refusal and public Microsoft documentation support the corrected guidance; elevated working-directory behavior is conditional."
    },
    {
      "check": "DR-7",
      "result": "pass",
      "evidence": "Four plan hashes and census counts reproduced; task linter and seven existing static tests pass; no new or live AC is claimed executed."
    },
    {
      "check": "DR-8",
      "result": "pass",
      "evidence": "Plan approval only; unsigned writable code, accepted option-A limits, firmware limits and required human execution gates remain disclosed."
    }
  ]
}
```

🕐 Completed: 2026-11-08 12:43 (EST)


## Corrections Applied — 2026-11-08, round 6 notes

The round-6 verdict is `approved` and stays as the reviewer wrote it. The coordinator applied the two Low notes as clerical fixes under the Materiality Gate, with no further round. The plan text changed on two lines only; the task file and every other line are unchanged.

| Note | Location | Change |
|------|----------|--------|
| F-025 | `implementation-plan.md` A-8 `reasoning` (line 1230) | "no connection to the member" became "no SSH call to the member: no admin check and no probe", and the line now says the TCP reachability check that picks the address (`fleet_usb.py:194`) still runs. A-8's chosen behavior and AC-18 are unchanged. |
| F-026 | `implementation-plan.md` AC-21 Negative Test (line 918) | Two negative copies added: a `usb/README.md` without the ordered steps (`import` on the hub, then a new or freshly formatted drive, then `prepare`) fails, and one without the warning that a format loses a record that `import` skipped or refused or that was written after the last `import` fails. WP-U7 and row 9 are unchanged. |

Checks after the fixes: the plan is 1464 lines, SHA-256 `f6a5ce8cfff67631c30275a6bc656f48526d915876e396148d96400681b717b6` (round-6 input `5b27773e80459f40df2b0a49714f4b1d7946bb360fe0102d8e8a464287153dcd`); the task file is unchanged at `a019e64eb42b696f39c977a0d60d5da369dcb98e2e982d3c7795e126391f0918`. No "no connection" text remains. Task lint passes (43 rows). The privacy scan has 0 hits over the three files. The D-1 and D-2 records, both briefs, the sudoers line and rows 3a and 7a are byte-identical to the round-5 input. The task file is parked at `approved` with `stop_gate: "released:human-gate"`; execution starts only on the human's typed proceed. The parking edit changes only the frontmatter, so the parked task file is SHA-256 `73e0e4eb8a6ec30fad29cadc90349924bfe10180f588dd85afe4acc18fbab675`.

🕐 Completed: 2026-11-08 12:46 (EST)


## Amendment — 2026-11-14 (D-3 A), input to round 7

The human typed "add PowerShell to the fleet requirments to be deployed on new members" and then chose option A: amend this parked plan with the PowerShell install for macOS and Linux members, with one more plan-review round. The project manifest already requires `pwsh` (`.agent/fleet.json:4`), and the member refuses a task without it (`fleet.py:1643` and `fleet.py:1789` raise `tool_missing:pwsh`). The Windows kit and `bootstrap.md` gain no PowerShell text (Out of Scope). D-1 and D-2 stay ruled A and their records are unchanged.

| Region | Change |
|--------|--------|
| User Review Required | New amendment paragraph (D-3 A); review limits now 7 rounds |
| WP table | New row WP-U6p; WP-U7 now depends on WP-U6p |
| WP-U5 step 11 | The PowerShell step runs before the CLI step |
| Named definitions | New: "PowerShell pin", "PowerShell step" |
| New section `### WP-U6p` (before WP-U7) | Pin steps 1–3 (`fetch_releases`, `pwsh_pin`, `prepare` writes `pwsh-pin.txt`); `install_pwsh` steps 1–7; trust note; Probe-3; PATH note; Boundary Inventory; AC-32; Spec Sufficiency; Files Modified |
| WP-U7 | `usb/README.md` PowerShell bullet; AC-21 negatives require `14 days`, `/usr/local/bin/pwsh`, `libicu` |
| WP-U8 | `AC_COUNT` 32; `check_live.py` mode `pwshpin`; the `linux` and `macos` modes print a `pwsh:` line and fail below major 7; AC-24 and AC-25 gain the text and negatives |
| Stop conditions | Condition 6 adds the PowerShell-step stops; new condition 13 |
| Out of Scope | Four new rows (Windows pwsh, `bootstrap.md` Unix sections, old-folder pruning, musl and other platforms) |
| Decision Log | D-3, A-19, A-20, A-21 |
| Research References | Microsoft install pages; PowerShell releases and the GitHub REST releases pages |
| `task.md` | Decisions line adds D-3; row 1 adds `pwshpin`; new row 8b (WP-U6p, Probe-3); row 9 depends on 8b; rows 13 and 14 require the `pwsh:` line; H1-6 records D-3 and the Probe-3 pin |

Hashes. Plan: before `f6a5ce8cfff67631c30275a6bc656f48526d915876e396148d96400681b717b6` (round-6 output, 1464 lines; no byte copy was kept), after `83395bb23c5a8a9d3d0e862701f8025cac5a2c14fe660d6495fea60a288cebb0` (1630 lines). Task: before `73e0e4eb8a6ec30fad29cadc90349924bfe10180f588dd85afe4acc18fbab675`, after `18547588096a16ac33b5332b149415caedce280f108739d8b28393f3f9b4cd03`. The byte copies are in the scratch folder `C:/Temp/zorivest/usb-kit-plan/amend-r7/` (`before/task.md`, `after/`). Because the round-6 plan has no byte copy, the reviewer reads the whole plan for regressions, not only the table above. Task lint passes (44 rows). The task stays parked at `approved` with `stop_gate: "released:human-gate"`.

🕐 Completed: 2026-11-14 (EST)


## Recheck (2026-11-14) — Round 7 of 7

Executing this plan should close the seven USB-kit gaps, retain the approved SSH and record safeguards, and add a hash-checked PowerShell installation for new macOS and Linux members under D-3 A. The amendment introduces two supported root-execution defects; those must be fixed before execution starts.

**Verdict: `changes_required`.** This is the last authorized plan-review round. The findings below are the record for the human; no eighth round, correction pass, implementation, commit or push is presumed. The human's reading at the plan-to-execution gate remains the terminating trust anchor. D-1 and D-2 stay ruled A.

### Findings

Here `plan` means `docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md`, and `task` means the adjacent `task.md`. Findings concern the instructions to be implemented, not claims that the new code or tests already exist. All findings were checked for a refutation against the current code, the complete plan and the cited primary sources before being retained.

| ID | Severity | Confidence | Must fix before execution | Finding and concrete failure | Evidence | Recommendation |
|---|---|---|---|---|---|---|
| F-027 | High | High | **yes** | The root-running `install_pwsh` probes an existing executable discovered through the account's login environment without specifying a privilege drop. An attacker who controls that account's `pwsh` gets its executable body run as root during setup, before it can print `7` and be left alone. | `plan:912-919`, `:397-399`, `:1469`; `.agent/fleet/usb/setup-unix.sh:122-128` | Discover and probe existing installations as the target account, with an explicit uid transition. Never run an account-controlled executable as root merely to obtain its version. Add an execution-identity negative. |
| F-028 | High | High | **yes** | The new archive install hardens the version folder but never establishes a protected physical ancestor chain for staging, the final binary or the bin link. A writable or redirected ancestor lets a local attacker replace the supposedly root-owned tree after extraction/hash verification and before the root version run, or replace the published link. | `plan:912-914`, `:929-937`, `:1469-1473`; compare the existing protection in `plan:201-206`, `:1542-1545`; stop 6 at `plan:1145-1147` names helper parents only | Before staging or root execution, establish/check the physical install and link-parent paths and reject unsafe owners, write permissions and redirects. Do not commandeer a package manager's writable directory. Add unsafe-parent/symlink negatives and a named stop. |
| F-029 | Medium | High | no | The absolute-path live fallback can report a good `pwsh:` version while the actual member process still cannot find PowerShell. The blanket PATH assurance does not cover a process with a restricted inherited PATH. This is a portability/documentation limit, not a demand to implement the excluded Unix bootstrap. | `plan:946-947`, `:1053-1055`, `:1119-1120`, `:1179`; `.agent/fleet/fleet.py:1465-1468`, `:1639-1645`, `:1788-1789`; `task:62-63` | State the member-process PATH prerequisite explicitly and describe the absolute-path check as installation evidence. When Unix member provisioning is implemented, verify lookup in that process's environment rather than inferring it from the SSH fallback. |
| F-030 | Medium | High | no | `fetch_releases` fetches one 50-item page, but A-21 promises the highest qualifying version across releases. A qualifying release outside that page is never considered: 50 more recently listed backports/previews can produce a lower pin or a false no-pin stop. The current observed pin is correct; the general selection guarantee is narrower than advertised. | `plan:899-908`, `:1489`; GitHub REST list parameters `page`/`per_page`; the captured response has `rel="next"` and `rel="last"` links | Follow pagination before choosing the integer maximum, or explicitly qualify and approve the bounded search rule. Retain a fixture where the winning candidate is on a later page. |
| F-031 | Low | High | no | In the written `tar -xzf --no-same-owner` fragment, `-f` consumes `--no-same-owner` as the archive filename. Both locally available tar implementations reject that form. The intended archive argument and corrected order are trivial to infer. | `plan:929` | Write `tar --no-same-owner -xzf "$archive" -C "$stage"`. This is a clerical command-fragment fix, not grounds to withhold approval. |
| F-032 | Low | High | no | Probe-3 is said to run before row 8b writes code, but it imports functions row 8b creates; the task correctly places it after the implementation/tests. Literal adherence to the former order gives a missing-import failure before the probe can run. | `plan:942-944`, `:1051-1053`; `task:44`, `:57` | Say that Probe-3 runs after its pure helpers exist and before any drive/member write, as row 8b already orders it; defer mode-specific imports until that mode runs. |
| F-033 | Low | High | no | The new age/stability/version predicate is stated in A-21 and restated as another operative predicate in the pin algorithm and AC-32. The spellings currently agree, but a correction to one can leave the other governing a different release choice. | `plan:902-904`, `:962`, `:1484-1493` | Keep A-21 as the canonical named selection predicate and reference it in the algorithm and AC. Human quotations, explanatory README text and boundary-test examples need not be erased. PR-9 clerical note only. |
| F-034 | Low | High | no | WP-U7's explicit prepare overwrite inventory omits the new `pwsh-pin.txt`, then says every other file is kept. The amended producer overwrites that generated file, so the retention inventory is now inaccurate. | `plan:909-910`, `:1010-1012`; `task:58` | Add the generated pin to the overwrite inventory. The not-a-reset rule and the prior F-024 resolution remain valid. |
| F-035 | Low | High | no | WP-U6p's context strategy is `shared` in the WP table but `compact_continue` in its task row. Executors are given conflicting context-lifecycle instructions for the new work. The task's explicit reread list makes the intended correction readily inferable. | `plan:74`; `task:57` | Make the WP table agree with row 8b's `compact_continue`, or choose the same strategy in both places. |

Only F-027 and F-028 contribute to `changes_required`. F-029/F-030 are nonblocking limits; F-031 through F-035 are nonblocking clerical notes under the Materiality Gate. No earlier fixed finding is reopened.

#### F-027 — refutation and privilege trace

The existing `has_cli` runs its account-shell lookup through `sudo -u "$user" -i` (`setup-unix.sh:122`), and the existing installer also runs as that account (`:128`). Those are useful precedents, but they do not supply the missing transition in the new contract: WP-U6p explicitly says `install_pwsh` runs as root, then says the step runs each discovered executable for its version. It expressly allows discovery in the account's login shell and gives no ownership restriction on that existing executable. A normal user-level PowerShell install is therefore an allowed input, not a forged plan or tampered drive.

`-NoProfile` and `-NonInteractive` constrain a genuine PowerShell host's behavior; they cannot constrain the body of an arbitrary executable called `pwsh`. A marker-only scratch executable accepted those arguments, ran its body and printed `7`. That probe did not elevate or run real PowerShell; the root consequence follows from the plan's stated caller identity. Root-owned new tarball files and A-20's hash check do not protect this pre-download branch. [Homebrew's primary ownership/privilege explanation](https://docs.brew.sh/FAQ#why-does-homebrew-say-sudo-is-bad) independently describes the same information-only-command privilege hazard. This violates PR-8's real privilege boundary and the hardening objective, rather than asking for a new scope feature.

#### F-028 — refutation and post-hash replacement trace

`--no-same-owner` is valid on both GNU tar and Apple's bsdtar. It prevents restoring archive owner IDs; the plan additionally requires owner/group 0 and removal of group/other write bits. Those measures protect the extracted object, but not its directory entry in a writable ancestor. For example, an existing account-writable or redirected `/usr/local/microsoft` can contain a root-owned `powershell/<version>` and still let that account replace the `powershell` entry. The next absolute `<install root>/<version>/pwsh` call then executes replacement bytes as root. A writable bin directory likewise permits replacing the published link. A package-manager-controlled directory is a realistic writable-parent case; it must not be treated as root-controlled merely because a child was chowned.

The already approved Helper definition states this exact filesystem principle and implements a physical-parent walk for `/opt/fleet-admin`. That walk does not visit the new PowerShell ancestors or `/usr/local/bin`; neither does the home/`.ssh` symlink stop. This is a new installation surface, not a deeper re-review of the fixed helper policy. Microsoft's [Linux archive instructions](https://learn.microsoft.com/en-us/powershell/scripting/install/alternate-install-methods) and [macOS archive instructions](https://learn.microsoft.com/en-us/powershell/scripting/install/install-powershell-on-macos) supply installation locations, not a guarantee about every member's existing ancestor ownership. The missing control must be bound to `main -> install_pwsh -> stage/final/link paths`, with rejection before root execution. No transaction or new signing scheme is required when protected parents establish the needed exclusion.

#### F-029 — reproduced failure, bounded by the actual exclusion

The scratch probe compiled only the real `Refuse` and `member_script` definitions from `fleet.py`; it did not import the module, load a client, open a stored configuration, or start a member. With a synthetic process PATH excluding the synthetic install bin, the real function raised `tool_missing:pwsh`. Calling the marker interpreter by absolute path returned `7.6.9`. Thus the proposed fallback and the production lookup can disagree. `capability_report -> tool_version` also uses `shutil.which`, and `agent_start` repeats that lookup. The source has no `/usr/local/bin/pwsh` fallback.

The attempted scope refutation succeeds in part: the MVP plan really leaves the Unix bootstrap sections empty (`2026-11-03-fleet-mvp/implementation-plan.md:290-292`, `:376`, `:526`), and the existing bootstrap tests enforce that (`test_fleet_bootstrap.py:247-250`). D-3 authorizes the install, not a Unix service/autostart implementation. Accordingly this finding is Medium and nonblocking: document the prerequisite and keep the installation check's claim narrow. It is not promoted to a scope-discipline blocker, and no bootstrap or fleet-code change is demanded here.

### Primary-source checks and attempted refutations

| Surface | Result |
|---|---|
| Pin fields, asset names and notes | The public REST snapshot contains `draft`, `prerelease`, `published_at`, the release body, and all four exact tarball names. Notes use a filename followed by its SHA-256 on the next nested-bullet line, with uppercase hash text. Each of the four 7.6.9 REST digests equals its notes hash ignoring case. [REST releases documentation](https://docs.github.com/en/rest/releases/releases), [PowerShell releases](https://github.com/PowerShell/PowerShell/releases/tag/v7.6.9). |
| Selection on the review date | At `2026-11-14T00:00:00Z`, the prescribed first-page integer selection yields **7.6.9**, published `2026-10-25T17:26:05Z`. Stable 7.7.0 and 7.6.10 were published November 10 and are too young; 7.7.0-rc.1 is a prerelease. Major/minor/patch integer ordering and the inclusive 14-day cutoff are correctly specified. All four assets must agree before fallback to an older complete candidate. F-030 concerns omitted pages, not a mismatched observed pin. |
| Missing digest or malformed metadata | A-20 requires a full `sha256:` digest and matching notes, not trust in an absent/null digest. An unrecognized/incomplete candidate is skipped with its reason, and none left stops prepare. The member needs neither a GitHub credential nor the release API for the pin. |
| Linux installation and dependencies | The archive method and architecture names are documented by Microsoft. Dependencies vary by distro; ICU is one of them, not a complete dependency list. Microsoft's [.NET dependency inventory](https://github.com/dotnet/core/blob/main/release-notes/10.0/dotnet-dependencies.md) names `libicu78` for Ubuntu 26.04, `libicu74` for 24.04 and `libicu` for RHEL. The plan's generic “distribution's libicu package” is understandable guidance, not an exact universally runnable package command. Failure of the version run stops/removes the new install and leaves no success record; a missing automatic dependency installer is not an omitted promised deliverable. |
| Supported platforms | The plan intentionally chooses glibc x64/arm64 Linux and macOS x64/arm64 tarballs. Microsoft documents supported OS versions separately; architecture alone does not establish support for every OS release. Unsupported/musl/dependency-incompatible builds must fail the launch/version check. No successful installation on an unsupported platform is inferred. Windows installation remains in `setup-member.ps1`. |
| Tar ownership and syntax | [GNU tar's option documentation](https://www.gnu.org/software/tar/manual/tar.html) and [Apple's bsdtar manual](https://raw.githubusercontent.com/apple-oss-distributions/libarchive/main/libarchive/tar/bsdtar.1) support `--no-same-owner`. A real tiny local archive extracted with the corrected form under GNU tar 1.35 and Windows bsdtar 3.8.9; the literal plan order failed on each. This is a local cross-check, not a macOS runtime result. |
| macOS quarantine/Gatekeeper | No blanket quarantine-removal defect survives source refutation. The planned transport is `curl` followed by `tar`; Apple's [trusted-execution guidance](https://developer.apple.com/forums/thread/706442) says those Unix tools do not set/propagate quarantine like browser/Finder downloads. Microsoft's current archive recipe uses the same transport. An OS policy/code-signature/dependency launch failure still takes the version-failure stop. No fresh macOS launch was performed, no Gatekeeper bypass is prescribed, and a browser-downloaded replacement workflow is not assumed. |
| Idempotence and existing installs | Once a valid existing 7+ interpreter is found, the operative contract skips download and replacement; reruns keep it even if prepare later selects a newer pin. A-19's explanation of installing beside an old version is not an upgrade requirement overriding that explicit skip. A lower/broken existing interpreter stops rather than being overwritten. A wrong hash is refused before extraction; a failed new version is removed before publication. F-027/F-028 remain necessary to make the security claims true. |
| Trust and security canon | The pin is public data with the same drive trust as the scripts. No independent drive authentication or author-forgery defense is invented. The hub fetches pin metadata without a token; the member's public asset download is distinct from selecting/fetching the pin. The earlier MVP D-4 A record explicitly narrows GitHub isolation to credentials and the fleet's own actions (`2026-11-03-fleet-mvp/implementation-plan.md:78-85`, `:637-650`); it is not an egress firewall. PowerShell adds no port, sign-in, credential or secret-bearing file. The existing SSH-kit exception to bootstrap's port wording remains WP-U7's scoped clarification. |

**Stop-path audit.** Network/JSON failure or no qualifying pin stops hub prepare before any file write (WP-U6p pin steps; stop 13). An existing older/broken pwsh, unknown OS/architecture, malformed/missing pin, download/hash failure, extraction/permission/move/link error, or launch/version failure must stop the member setup; step 7 supplies temp cleanup, and the global Record retire rule prevents a stale success record. Stop 6 covers the PowerShell check failures and stop 8 covers any secret in evidence. The new unsafe-executable and unsafe-parent cases are not presently stopped at all: they can print the expected version and succeed. Those are F-027/F-028, rather than a request to restate every I/O error in the enumerated stop list. The finite-release-window false no-pin is F-030. Probe-3's sequencing contradiction is clerical F-032.

### Regression, decisions and complete coverage

The entire 1,630-line plan and entire task file were read, not just amendment regions. There is no byte copy of the round-6 plan, so no byte-identical whole-plan comparison to that output is claimed. Current hashes match the amendment's declared inputs:

- Plan: `83395bb23c5a8a9d3d0e862701f8025cac5a2c14fe660d6495fea60a288cebb0`.
- Task: `18547588096a16ac33b5332b149415caedce280f108739d8b28393f3f9b4cd03`.
- Parked pre-amendment task: `73e0e4eb8a6ec30fad29cadc90349924bfe10180f588dd85afe4acc18fbab675`.

The full parked/current task diff changes only the Decisions paragraph and rows 1, 9, 13, 14 and H1-6, and adds 8b. Both ruling rows 3a/7a are unchanged. D-1/D-2 Decision Log entries, both complete briefs and the complete two-line Sudoers definition are byte-identical as text to the earlier preserved round-5 input; round 6 recorded these same sections as unchanged. Both rulings retain the human's typed 2026-11-08 A. Neither is re-decided.

Against that preserved input, the only changed prior AC IDs are 21, 24 and 25: AC-21 contains the approved drive-guidance correction, both round-6 Low corrections, and the new PowerShell paragraph requirement; AC-24/25 add the PowerShell line. Every other AC row is unchanged. The Password-off, Record retire, fingerprint/pin refusal, firewall/runtime target, helper environment, fresh-evidence and privacy meanings remain intact. Stop conditions 1–12 are unchanged except the declared addition to 6; 13 is new. F-025's corrected no-SSH wording and F-026's two whole-guidance deletion negatives are present. F-034 is a new generated-file inventory omission, not a reopening of F-024's drive-authentication boundary.

| Scope | Exhaustive coverage/result |
|---|---|
| Work packages and dependencies | All 11 WP rows: U1, U2, U3, U4, U5, U5w, U5b, U6, U6p, U7, U8. The WP chain is acyclic; U6p is between U6 and U7, and row 8b depends on 8a. F-035 is only a strategy label mismatch. |
| Named definitions | All **24**: Kit; Drive folder; Helper; Mode reader; Sudoers file; Drop-in; Marked block; Key-auth check; Password-off check; Record retire; Listener check; Firewalld rules; Firewalld checks; SSH rule report; Member subnets; Load guard; Git bash; Stub folder; Admin check; Outcomes; Probe; Console guard; PowerShell pin; PowerShell step. The two new definitions lead to the planned production producers; the new executable trust boundaries need F-027/F-028. |
| AC-1..AC-7 | Constants/retired-word consumer chain, hello update order, load guards, shell versions, line ends, encoding and privacy remain aligned with rows 2/2a/3. |
| AC-8..AC-13, AC-26, AC-28 | Helper verbs, owners/parent walk, sudoers environment/policy checks, admin outcomes, Windows profile/report, characterization and Git bash locator remain as approved. |
| AC-14..AC-20, AC-27, AC-31 | Both platform halves of guards and retirement, Unix firewall/listener/zone behavior, key-auth/password-off rollback, probe, image signature, conditional CLI verification and pin refusal retain their meanings and explicit negatives. D-1/D-2 controls are unchanged. |
| AC-21..AC-25, AC-29..AC-30 | Documentation and package/state/privacy gates remain scheduled. PowerShell README and live-line additions were read in full; F-029 bounds the live-line claim and F-034 corrects the overwrite inventory. |
| AC-32 | Selection fixtures, exact age boundary, numeric version ordering, missing asset/hash disagreement fallback, no-write failure, archive installation, existing-version handling and wrong-hash/version negatives all read. Hash-before-extraction and link-after-launch order are explicit; no privileged-trust negative currently closes F-027/F-028. |
| Task rows PC, 0, 1, 2, 2a, 3, 3a, 4, 5, 6, 6a, 7, 7a, 8, 8a, 8b, 9, 10–15 | Every Task, Owner, Deliverable, Validation, dependency, context strategy, durable output, model and status cell read. New mode imports can be lazy until 8b; no missing executable is mistaken for an existing gate. |
| Task rows H1-1..H1-7b, H2-1..H2-6, COMMIT | Every closeout/review/identity/known-issue/reflection/privacy/commit/finalization row read, including H1-6a/H1-6b, H1-7a/H1-7b and H2-3a/H2-3b/H2-3c. The independent execution-review barrier and human commit/proceed gates remain intact. |
| Counts and artifact existence | **44 task rows**, all unchecked, dependencies resolve with no cycle; **32 AC IDs**, **34 AC table rows** because 14 and 27 each have two halves; `AC_COUNT` **32**; 24 definitions. Every invoked executable/test/schema/config path is present or has a preceding creation task, or is an explicit absence/no-op check. Implementation handoff remains absent. |
| Out of Scope | Every old row and all four new rows checked. Windows pwsh is covered by existing setup-member scope; the Unix-bootstrap exclusion is real canon; old-folder pruning is not required for the selected link; musl/other architectures are expressly rejected or fail launch. No required privilege check is excused by these exclusions. F-029 remains nonblocking in light of that canon. |

**PR-6 continuity.** The previous corrections' raw census and per-hit disposition map still exist and agree: 1,008 searches, 3,697 hits, 191 updated, 3,506 confirmed-consistent and 304 explicit zero-hit rows. Round 6 independently audited that historical state. This round reproduced those counts and inspected the disposition structure; it does not claim to have re-run the old final-line mapping against today's amended line numbers. The coordinator's two round-6 notes have their exact per-note disposition at review:2315-2318. The new D-3 material is a human-authorized scope amendment, reviewed here at initial-review depth, not an undispositioned correction resubmission. The amendment's region/hash inventory, complete reread and parked task diff provide its input identity. No procedural gate is used to avoid the substantive review.

**Usability and complexity.** The ICU human stop is explicit and reversible. Existing pwsh 7+ installs are deliberately retained, not silently upgraded. No extra signing, service manager, package-manager replacement or credential mechanism is proposed. Findings are tied to the concrete privileged-execution failures, the PATH lookup disagreement, the finite-page selection counterexample or directly inferable clerical corrections. No preference-only simplification is a blocker.

### Executed verification and limits

Reviewer receipts and harmless fixtures are under `review receipts in C:/Temp/zorivest/usb-kit-plan/review-r7/`:

- `audit.py`, `audit.txt`, `input-hashes.json`, `task-diff.txt`, `review-before.md`: hashes, all row/AC/definition inventories, task DAG, parked task diff, public release metadata comparison.
- `releases-50.json`, `releases-headers.json`: unauthenticated public REST bytes and pagination headers; no binary download.
- `source_audit.py`, `source-audit.txt`: decision/brief/sudoers immutability, AC/stop/task differences, artifact inventory, prior census counts, untruncated new-literal census and public documentation snapshots.
- `probes.py`, `probes.txt`: real isolated fleet lookup against a synthetic PATH, absolute marker fallback, version-argument marker, and GNU/bsdtar archive syntax checks. The first GNU-tar fixture invocation used a Windows drive-colon path and failed to resolve it as an archive host; the final successful run uses a local POSIX path. No remote archive was opened.
- `task-lint.txt`: exit 0; **44 rows**, contract checks and acyclic dependencies pass.
- `existing-static-tests.txt`: exit 0; **7 passed, 316 deselected in 0.60s**, covering bootstrap text/deletion checks and the unchanged forbidden-command set. Run with `-B`, `-p no:cacheprovider` and a basetemp in this review's scratch folder.

Commands included read-only `rtk git status --short`, unfiltered `rtk proxy rg`, complete file reads, the allowed task lint, the selected existing pytest tests, public HTTPS reads, and the named scratch scripts. No setup, launcher, hub/member/run command, SSH connection, real PowerShell install, sudo, git write or credential/key/token read was performed. No live AC, future test suite, full regression suite or Pester suite is claimed executed. All four separately owned dirty kit files and both plan files remain unchanged; post-write verification checks their hashes and preservation of the prior review text.

### Checklist results

| Check | Result | Evidence |
|---|---|---|
| PR-1 | pass | Complete plan/task read; all 44 rows align in scope/order; F-032/F-035 are inferable clerical labels/order prose. |
| PR-2 | pass | All 44 statuses unchecked; implementation handoff absent; four dirty kit files belong to the other session. |
| PR-3 | pass | Task lint passes required fields, receipt/exit rules and dependencies. |
| PR-4 | partial | Runnable artifacts exist or are scheduled. F-029/F-030 limit what the new checks prove; F-031 is nonblocking syntax shorthand. |
| PR-5 | pass | D-3 and A-19..A-21 traced to typed approval and primary Microsoft/GitHub sources; platform/dependency and quarantine claims checked. |
| PR-6 | pass | Prior census/map continuity reproduced, round-6 note dispositions retained; new amendment identity and full review recorded above. |
| PR-7 | pass | All exclusion bases inspected; Unix bootstrap really is excluded by the MVP canon. F-029 does not invent that implementation scope. |
| PR-8 | fail | F-027 runs an untrusted existing executable with the installer's privilege; F-028 lacks a producer for protected PowerShell ancestors before root execution. |
| PR-9 | pass | Full new-literal census retained; current numeric spellings agree. F-033 is a Low single-statement correction note, not an ambiguous behavior blocker. |
| DR-1 | pass | Amendment describes pending work, not implemented code; hashes and current source support the factual baseline. |
| DR-2 | pass | F-025's old no-connection wording removed; F-026 negatives retained; earlier fixed security surfaces not reopened. |
| DR-3 | pass | New WP/AC/mode/task/handoff references resolve; F-034/F-035 are readily inferable inventory/strategy corrections. |
| DR-4 | partial | Isolated production lookup exposes F-029's evidence limit; privilege negatives for F-027/F-028 remain required. |
| DR-5 | pass | Exact public metadata, source snapshots, scratch probes, lint and selected-test receipts retained. |
| DR-6 | partial | Primary platform and asset claims check out; new privileged-path rules and the global release-selection claim need the recorded corrections. |
| DR-7 | pass | Declared input hashes, row/definition/AC counts and prior census totals reproduced; no live result inferred. |
| DR-8 | pass | Plan remains unstarted; accepted drive, D-1/D-2 and platform limits disclosed; approval or execution completion not falsely claimed. |

### Verdict and human handback

**Changes required before execution: F-027 and F-028.** The other seven findings are nonblocking notes under the workflow's threshold. The last authorized round has ended, so the human receives this complete record and decides the next gate. Any authorized correction work belongs in `/plan-corrections`; this review does not start it or presume another review round.

The writable-drive trust rule, first-import fingerprint comparison, configured-package root residual under D-1 A, full Windows administrator, D-2's installer-before-binary-check exposure, unsupported-platform/dependency stops and lack of Unix bootstrap remain stated limits. No author-forgery defense or additional human design choice is smuggled into the verdict.

### Structured verdict — Round 7

```json
{
  "schema_version": "review-verdict.v1",
  "date": "2026-11-14",
  "review_mode": "plan",
  "target_plan": "docs/execution/plans/2026-11-07-usb-kit-hardening",
  "agent": "Codex",
  "requested_verbosity": "detailed",
  "verdict": "changes_required",
  "summary": "Round 7 of 7: F-027 and F-028 must be fixed before execution: existing user-controlled pwsh is probed as root, and new PowerShell install/link ancestors are not protected. Two Medium limits and five Low notes are nonblocking. All 44 task rows, 24 definitions and 32 AC IDs reviewed; task lint and seven static tests pass. D-1/D-2 remain A. Full record: .agent/context/handoffs/2026-11-07-usb-kit-hardening-plan-critical-review.md. Last-round handback to the human; no implementation or further round authorized.",
  "findings": [
    {
      "id": "F-027",
      "severity": "High",
      "confidence": "High",
      "finding": "The root-running `install_pwsh` probes an existing executable discovered through the account's login environment without specifying a privilege drop. An attacker who controls that account's `pwsh` gets its executable body run as root during setup, before it can print `7` and be left alone.",
      "file_line": "docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:912; docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:916; .agent/fleet/usb/setup-unix.sh:122",
      "recommendation": "Discover and probe existing installations as the target account, with an explicit uid transition. Never run an account-controlled executable as root merely to obtain its version. Add an execution-identity negative.",
      "status": "open"
    },
    {
      "id": "F-028",
      "severity": "High",
      "confidence": "High",
      "finding": "The new archive install hardens the version folder but never establishes a protected physical ancestor chain for staging, the final binary or the bin link. A writable or redirected ancestor lets a local attacker replace the supposedly root-owned tree after extraction/hash verification and before the root version run, or replace the published link.",
      "file_line": "docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:929; docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:932; docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:201",
      "recommendation": "Before staging or root execution, establish/check the physical install and link-parent paths and reject unsafe owners, write permissions and redirects. Do not commandeer a package manager's writable directory. Add unsafe-parent/symlink negatives and a named stop.",
      "status": "open"
    },
    {
      "id": "F-029",
      "severity": "Medium",
      "confidence": "High",
      "finding": "The absolute-path live fallback can report a good `pwsh:` version while the actual member process still cannot find PowerShell. The blanket PATH assurance does not cover a process with a restricted inherited PATH. This is a portability/documentation limit, not a demand to implement the excluded Unix bootstrap.",
      "file_line": "docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:946; docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:1053; .agent/fleet/fleet.py:1639",
      "recommendation": "State the member-process PATH prerequisite explicitly and describe the absolute-path check as installation evidence. When Unix member provisioning is implemented, verify lookup in that process's environment rather than inferring it from the SSH fallback.",
      "status": "open"
    },
    {
      "id": "F-030",
      "severity": "Medium",
      "confidence": "High",
      "finding": "`fetch_releases` fetches one 50-item page, but A-21 promises the highest qualifying version across releases. A qualifying release outside that page is never considered: 50 more recently listed backports/previews can produce a lower pin or a false no-pin stop. The current observed pin is correct; the general selection guarantee is narrower than advertised.",
      "file_line": "docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:899; docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:1489",
      "recommendation": "Follow pagination before choosing the integer maximum, or explicitly qualify and approve the bounded search rule. Retain a fixture where the winning candidate is on a later page.",
      "status": "open"
    },
    {
      "id": "F-031",
      "severity": "Low",
      "confidence": "High",
      "finding": "In the written `tar -xzf --no-same-owner` fragment, `-f` consumes `--no-same-owner` as the archive filename. Both locally available tar implementations reject that form. The intended archive argument and corrected order are trivial to infer.",
      "file_line": "docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:929",
      "recommendation": "Write `tar --no-same-owner -xzf \"$archive\" -C \"$stage\"`. This is a clerical command-fragment fix, not grounds to withhold approval.",
      "status": "open"
    },
    {
      "id": "F-032",
      "severity": "Low",
      "confidence": "High",
      "finding": "Probe-3 is said to run before row 8b writes code, but it imports functions row 8b creates; the task correctly places it after the implementation/tests. Literal adherence to the former order gives a missing-import failure before the probe can run.",
      "file_line": "docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:942; docs/execution/plans/2026-11-07-usb-kit-hardening/task.md:57",
      "recommendation": "Say that Probe-3 runs after its pure helpers exist and before any drive/member write, as row 8b already orders it; defer mode-specific imports until that mode runs.",
      "status": "open"
    },
    {
      "id": "F-033",
      "severity": "Low",
      "confidence": "High",
      "finding": "The new age/stability/version predicate is stated in A-21 and restated as another operative predicate in the pin algorithm and AC-32. The spellings currently agree, but a correction to one can leave the other governing a different release choice.",
      "file_line": "docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:902; docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:962; docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:1489",
      "recommendation": "Keep A-21 as the canonical named selection predicate and reference it in the algorithm and AC. Human quotations, explanatory README text and boundary-test examples need not be erased. PR-9 clerical note only.",
      "status": "open"
    },
    {
      "id": "F-034",
      "severity": "Low",
      "confidence": "High",
      "finding": "WP-U7's explicit prepare overwrite inventory omits the new `pwsh-pin.txt`, then says every other file is kept. The amended producer overwrites that generated file, so the retention inventory is now inaccurate.",
      "file_line": "docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:909; docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:1011",
      "recommendation": "Add the generated pin to the overwrite inventory. The not-a-reset rule and the prior F-024 resolution remain valid.",
      "status": "open"
    },
    {
      "id": "F-035",
      "severity": "Low",
      "confidence": "High",
      "finding": "WP-U6p's context strategy is `shared` in the WP table but `compact_continue` in its task row. Executors are given conflicting context-lifecycle instructions for the new work. The task's explicit reread list makes the intended correction readily inferable.",
      "file_line": "docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:74; docs/execution/plans/2026-11-07-usb-kit-hardening/task.md:57",
      "recommendation": "Make the WP table agree with row 8b's `compact_continue`, or choose the same strategy in both places.",
      "status": "open"
    }
  ],
  "checklist_results": [
    {
      "check": "PR-1",
      "result": "pass",
      "evidence": "Complete plan/task read; all 44 rows align in scope/order; F-032/F-035 are inferable clerical labels/order prose."
    },
    {
      "check": "PR-2",
      "result": "pass",
      "evidence": "All 44 statuses unchecked; implementation handoff absent; four dirty kit files belong to the other session."
    },
    {
      "check": "PR-3",
      "result": "pass",
      "evidence": "Task lint passes required fields, receipt/exit rules and dependencies."
    },
    {
      "check": "PR-4",
      "result": "partial",
      "evidence": "Runnable artifacts exist or are scheduled. F-029/F-030 limit what the new checks prove; F-031 is nonblocking syntax shorthand."
    },
    {
      "check": "PR-5",
      "result": "pass",
      "evidence": "D-3 and A-19..A-21 traced to typed approval and primary Microsoft/GitHub sources; platform/dependency and quarantine claims checked."
    },
    {
      "check": "PR-6",
      "result": "pass",
      "evidence": "Prior census/map continuity reproduced, round-6 note dispositions retained; new amendment identity and full review recorded above."
    },
    {
      "check": "PR-7",
      "result": "pass",
      "evidence": "All exclusion bases inspected; Unix bootstrap really is excluded by the MVP canon. F-029 does not invent that implementation scope."
    },
    {
      "check": "PR-8",
      "result": "fail",
      "evidence": "F-027 runs an untrusted existing executable with the installer's privilege; F-028 lacks a producer for protected PowerShell ancestors before root execution."
    },
    {
      "check": "PR-9",
      "result": "pass",
      "evidence": "Full new-literal census retained; current numeric spellings agree. F-033 is a Low single-statement correction note, not an ambiguous behavior blocker."
    },
    {
      "check": "DR-1",
      "result": "pass",
      "evidence": "Amendment describes pending work, not implemented code; hashes and current source support the factual baseline."
    },
    {
      "check": "DR-2",
      "result": "pass",
      "evidence": "F-025's old no-connection wording removed; F-026 negatives retained; earlier fixed security surfaces not reopened."
    },
    {
      "check": "DR-3",
      "result": "pass",
      "evidence": "New WP/AC/mode/task/handoff references resolve; F-034/F-035 are readily inferable inventory/strategy corrections."
    },
    {
      "check": "DR-4",
      "result": "partial",
      "evidence": "Isolated production lookup exposes F-029's evidence limit; privilege negatives for F-027/F-028 remain required."
    },
    {
      "check": "DR-5",
      "result": "pass",
      "evidence": "Exact public metadata, source snapshots, scratch probes, lint and selected-test receipts retained."
    },
    {
      "check": "DR-6",
      "result": "partial",
      "evidence": "Primary platform and asset claims check out; new privileged-path rules and the global release-selection claim need the recorded corrections."
    },
    {
      "check": "DR-7",
      "result": "pass",
      "evidence": "Declared input hashes, row/definition/AC counts and prior census totals reproduced; no live result inferred."
    },
    {
      "check": "DR-8",
      "result": "pass",
      "evidence": "Plan remains unstarted; accepted drive, D-1/D-2 and platform limits disclosed; approval or execution completion not falsely claimed."
    }
  ]
}
```


🕐 Completed: 2026-11-14 18:40 (EST)


## Corrections Applied — 2026-11-14, round 7

Applied by the plan's author. This section is not an approval. All earlier text in this file is unchanged, the frontmatter included; only an independent reviewer can set `approved`.

This pass covers F-027 to F-035 of round 7. Each finding was checked against the cited plan lines and held; none is dismissed. All corrections are plan text. No code file, no kit file and no test was changed. Line numbers are for the final files: `plan` is `implementation-plan.md` and `task` is `task.md`.

Direction in this pass:

- **Human direction.** On 2026-11-14, after round 7, the human typed "fix all findings and run more review round" and confirmed that it is for this plan. The plan loop gets an eighth round, and round 8 is the next review (plan:90-92, :120-121; task:36). The token budget stays 10,500,000, as in round 5 ("6 plan rounds share the unchanged 10,500,000-token budget", review:2030).
- **D-1, D-2 and D-3 stay ruled A.** Their Decision Log entries are byte-identical to the text before this pass (`dcheck.txt`), the D-3 reasoning line "adds round 7 to the plan loop by the same typed A" included.
- **Task parked.** `status: "approved"` and `stop_gate: "released:human-gate"` are unchanged; task lines 1-8 are byte-identical.

| Item | Disposition | Correction | Where |
|---|---|---|---|
| F-027 | fixed | New **Execution identity** paragraph, the one place that states who runs each program: a `pwsh` that the step finds and did not install runs only as the account, through `sudo -u "$user" -i`, as `has_cli` does (`setup-unix.sh:122`); root never runs it and never runs `command -v pwsh` in its own shell; the system tools run as root, only inside folders that pass the Parent walk; root runs only `<install root>/<version>/pwsh`, after the hash check and a second walk. Step 1 now finds `pwsh` through the account's login shell plus a file test of `<bin dir>/pwsh`, and runs each path as the account; a `pwsh` that does not run as the account stops. `install_pwsh` takes a `<user>` argument. AC-32 adds a fake account-owned `pwsh` that writes a marker with `id -u`, run only through the stub `sudo -u <user> -i`; a marker for uid 0 or root fails the test. Stop condition 6 names the account-run failure. | plan:407-409, :925-944, :1003, :1010, :1021, :1198-1206, :1523-1532 (A-19); task:57 (row 8b) |
| F-028 | fixed | New Named definition **Parent walk**: the folder and each parent up to `/`, on the physical path, must have owner 0 and no group or other write bit; a sticky bit does not excuse a write bit; a failed walk names the path. The Helper and the PowerShell step both use it, and the Helper definition, the helper's refusal text, its Spec Sufficiency row, its Files row and the Decision Brief text now refer to it by name. Step 4 walks `<install root>` and `<bin dir>` before any write, requires each path to equal its `pwd -P` path, makes missing folders with `install -d -m 755 -o 0 -g 0`, and never changes the owner or mode of a folder that it did not make. A bin dir that a package manager gave to the account (Homebrew's `/usr/local/bin` on an Intel Mac) stops the setup. The download goes into `<install root>/.dl-<pid>` (mode 700) and the stage is `<install root>/<version>.new`, so no file goes in a world-writable temp folder. Step 7 walks the version folder again and requires a regular root `pwsh`; step 8 walks the bin dir again before `ln -sfn`. AC-32 adds stub `stat` and `sudo`, a `.dl-<pid>` curl output path, parents with a user owner, mode 0777 and mode 1777, a user-owned bin dir, and symlinked install root and bin dir, each stopping before `curl`, `tar`, the new `pwsh` or `ln`. A new Boundary Inventory row covers the folders. User Review Required flag 12 names the Homebrew stop. | plan:155-157, :208-216, :528, :571, :577, :950-977, :1004, :1010, :1021, :1028, :1198-1206, :1523-1532 (A-19), :1602-1603 |
| F-029 | fixed | New paragraph **The member process's `PATH`**: the fleet finds `pwsh` with `shutil.which` in the member process's own environment (`fleet.py:1466`, `:1641-1643`, `:1788-1789`); the live `pwsh:` checks are installation evidence only; that lookup is a prerequisite of the Unix member process, which a later plan must check. WP-U8, AC-24, AC-25, rows 13 and 14, the Out of Scope row and a new Risks bullet say the same. | plan:190-191, :987-993, :1104-1111, :1174, :1175, :1238; task:62, :63 |
| F-030 | fixed | Step 1 asks for `per_page=100` and follows the `Link` header's `rel="next"` only on `https://api.github.com/`, for at most 10 pages. If page 10 still has a next link, `prepare` stops with "the PowerShell release list has more than 10 pages" (stop condition 13) and writes nothing; a next link on another host also stops. The bounded-search alternative was not chosen. AC-32 adds a paged fixture whose winner is on page 2, a page-10 cap case and a foreign-host case. New Boundary Inventory row for the `Link` header; new Spec Sufficiency row cites GitHub's pagination page. | plan:909-915, :1000, :1010, :1020, :1217-1219; task:57 |
| F-031 | fixed | Step 6 now reads `tar --no-same-owner -xzf "$archive" -C "$stage"`; A-19 states the same form. | plan:964-967, :1528 |
| F-032 | fixed | Probe-3 runs after `fetch_releases` and `pwsh_pin` exist and their AC-32 tests pass, and before any drive folder or member is written; it reads all pages. `check_live.py` imports a mode's functions only when that mode runs, so its other modes and `--selftest` run before row 8b. | plan:981-985, :1104-1106; task:44 (row 1), :57 (row 8b) |
| F-033 | fixed | A-21's `chosen` is now "the selection predicate", with the order over every page and the pin as the first release that passes A-20, and it says that it is the one place that states the predicate. WP-U6p step 2, the PowerShell pin definition, the Boundary Inventory row and AC-32 refer to it by name and do not restate it. | plan:404-406, :916-917, :999, :1010, :1543-1552 |
| F-034 | fixed | WP-U7's not-a-reset list now names `pwsh-pin.txt` among the files that `prepare` rewrites; row 9 says the same. The README PowerShell bullet adds the account-only run and the Homebrew stop. | plan:1061-1062, :1071-1075; task:58 |
| F-035 | fixed | The WP-U6p strategy is `compact_continue`, with the re-read list: `task.md`, D-3, A-19 to A-21, the WP-U6p section, AC-32 and the outputs. This matches row 8b. | plan:74; task:57 |

No new AC was added; every change extends AC-32, AC-24 or AC-25. `AC_COUNT` stays 32. The plan now has 25 Named definitions (24 before).

Stale-wording sweep of the final plan and task: `per_page=50`, `mktemp -d`, the old tar order `tar -xzf --no-same-owner`, root's own `command -v pwsh`, a temp download folder, "that definition's walk" and the old Probe-3 timing have no hits. "temp folder" remains only in the Stub folder definition (a test fixture) and in step 5's "No file goes in a world-writable temp folder". "before it writes code" remains only in WP-U8's `--red` mode, which is unrelated. "seventh" remains in the history of the amendment, with the eighth round stated after it.

Verification:

- `python core/tools/lint_task_contract.py --task docs/execution/plans/2026-11-07-usb-kit-hardening/task.md`: `OK: 44 row(s)`, exit 0 (`lint-task.txt`).
- `python -X utf8 -B -m pytest scripts/tests/test_fleet_bootstrap.py scripts/tests/test_fleet_agent.py -q -p no:cacheprovider -k "(test_ac19_the and not effort) or test_ac32_forbidden"`: 7 passed, 316 deselected, exit 0 (`pytest-static.txt`). The seven are the six `test_fleet_bootstrap.py` AC-19 cases and `test_fleet_agent.py::test_ac32_forbidden_commands_are_unchanged`. A first selector without `and not effort` also took `test_fleet_agent.py::test_ac19_the_effort_values_are_the_credits_schemas` and gave 8 passed (`pytest-collect.txt`).
- Both YAML blocks of the plan parse, and A-19, A-21 and D-3 read back (`yaml-check.txt`).
- No AC was executed, because every correction is plan text and the code does not exist yet.

Hashes and line counts (both files LF):

- `implementation-plan.md`: before `83395bb23c5a8a9d3d0e862701f8025cac5a2c14fe660d6495fea60a288cebb0` (1630 lines), after `2b003d730f4cce45e074e84a65f024b5618a32a27f69cd34323f31e1bc61fab3` (1689 lines).
- `task.md`: before `18547588096a16ac33b5332b149415caedce280f108739d8b28393f3f9b4cd03` (110 lines), after `651dd68482f25d1875678984953d86db39dbd7d8666825afa0de330d5b7784f9` (110 lines, 44 rows; lines 36, 44, 57, 58, 62 and 63 changed).

There is no byte copy of the round-6 plan. The round-7 input exists as byte copies in `C:/Temp/zorivest/usb-kit-plan/amend-r7/after/` and `C:/Temp/zorivest/usb-kit-plan/corrections-r7/before/`; the output is in `corrections-r7/after/`. The diffs are `corrections-r7/plan-diff.txt` and `corrections-r7/task-diff.txt`. No blast-radius census ran in this pass; the reviewer can read the diffs against the before copies.

Residual risks:

- A member with Homebrew on an Intel Mac now stops at the PowerShell step, because `/usr/local/bin` belongs to the account. The plan's stated way out is that the account installs PowerShell 7 first, so the rerun leaves it alone (flag 12). The human can choose another way at the plan gate.
- The live rows prove the installation, not the member process's `PATH` lookup; that waits for the Unix member plan.
- The 10-page limit is a fixed number. A release list longer than 1000 entries stops `prepare` until a plan gate raises the limit.
- 8 plan rounds share the unchanged 10,500,000-token budget.

**Open human decisions:** none is required to start round 8. The Homebrew stop (flag 12) is the one behavior that the human may want to change.

Not resolved:

- The four kit files that another session changed (`install-usb/README.md`, `usb/README.md`, `usb/setup-unix.sh`, `usb/setup-windows.ps1`) were not edited. The `setup-unix.sh:122` reference is to that working copy.
- No independent census audit ran in this pass.

🕐 Completed: 2026-11-14 (EST)


## Recheck (2026-11-14) — Round 8 of 8

**Intent anchor:** Executing this plan should close the seven kit findings while preserving administrative access, limiting privilege and network exposure, verifying downloads, and supplying usable tests and public documentation. This round cannot certify that the corrected plan delivers that objective: the mandatory correction-evidence precondition fails before substantive recheck.

**Verdict: `changes_required` — PR-6 procedural exception only. Final-round handback to the human.**

### F-036 — Current correction blast-radius census is missing

**Confidence: High. Procedural precondition; no delivery-level severity assigned.**

Evidence: the correction section at `.agent/context/handoffs/2026-11-07-usb-kit-hardening-plan-critical-review.md:2709` explicitly states, “No blast-radius census ran in this pass”. Its table at :2681–2691 supplies F-027 through F-035 dispositions and selected line references, but no raw census or map giving each matching `file:line` an `updated` or `confirmed-consistent` disposition. The recursive inventory of the current correction folder and text searches found no equivalent current receipt/map. The exact violated rule is `core/.agent/workflows/plan-critical-review.md:256` (PR-6), reinforced by :287–291 and `core/.agent/workflows/plan-corrections.md:182–231` (Step 5c).

**Attempted refutation:** The before/after byte copies, declared hashes, full diffs, per-finding correction table and stale-wording summary are available. Independent comparison confirms that both current files equal the correction pass's after copies and match all four declared before/after hashes. Those artifacts establish which text changed; they do not inventory every occurrence of changed values, including unchanged sites outside diff hunks, or disposition each hit. Searches in the current receipts find historical census descriptions and historical receipt filenames, not a census/map for these corrections. Round 7's PR-6 continuity explanation at :2435 concerned the initial D-3 scope amendment; it does not exempt this explicitly labelled correction resubmission. No author-forgery theory is involved. F-014's historical resolution is untouched; F-036 concerns a new submission with its own missing evidence.

**Concrete failure:** The resubmission lacks the evidence required to enter the substantive recheck. PR-6 expressly directs: “return `changes_required` naming only that, and do not review the corrected content this round”. The Verdict Rule makes this the sole exception to the High/Critical blocking threshold. This is not a Low clerical defect promoted into a security blocker.

**Required handback:** The human receives this record at the eight-round cap. The missing evidence consists of unfiltered, untruncated old/new and semantic-variant sweeps across both plan files, explicit zero-hit results and command exits, and a per-hit correction-log map. This review authorizes neither another review round nor execution. The human decides the next step; no automatic corrections or workflow chaining follows.

### Prior findings and review limits

The coordinator reports F-027 through F-035 fixed at :2683–2691. **All nine remain independently unverified in round 8**, rather than being rejected, reopened or certified fixed. In particular, the execution-identity trace for F-027 and the physical-ancestor trace for F-028 were not reached; the prior two High blockers have no independent closure from this round. No new High/Critical delivery finding is asserted.

D-1, D-2 and D-3 remain the human's A rulings; none is re-decided. Byte-identity of their records, AC/stop-condition preservation, pagination semantics and fixtures, every task row/definition/AC, dependency/cross-reference consistency, and bootstrap security regression checks are **not certified this round**. No inferred or inherited checklist pass substitutes for those checks. No public documentation or metadata request, task lint, fleet test, Pester test, parse check or live probe was needed or run to resolve the precondition.

### Input identity and executed verification

Read the workflow and its PR-6/Verdict Rule, correction workflow Step 5c, round-7 record and complete new correction section. Inspected read-only git status, recursively inventoried the 54 current correction files, searched their text for census/disposition evidence, and independently generated full unified diffs from the supplied before byte copies. Diff capture establishes input identity only; it is not a substantive review of changed content.

| File | Before SHA-256 | Current SHA-256 | Independent comparison |
|---|---|---|---|
| `implementation-plan.md` | `83395bb23c5a8a9d3d0e862701f8025cac5a2c14fe660d6495fea60a288cebb0` | `2b003d730f4cce45e074e84a65f024b5618a32a27f69cd34323f31e1bc61fab3` | 1,630 → 1,689 lines; 21 unified-diff hunks; equals after copy |
| `task.md` | `18547588096a16ac33b5332b149415caedce280f108739d8b28393f3f9b4cd03` | `651dd68482f25d1875678984953d86db39dbd7d8666825afa0de330d5b7784f9` | 110 → 110 lines; 3 unified-diff hunks; equals after copy |

Scratch evidence: `review receipts C:/Temp/zorivest/usb-kit-plan/review-r8/` contains `audit_inputs.py`, `input-audit.json`, complete `implementation-plan.md.diff` and `task.md.diff`, `review-before.md`, `workflow-reread.txt`, `stamp.txt`, and the review writer/verification script. Raw diff files are not represented as a correction census. The schema validation and preservation assertions pass; only this review file changes in the repository. Plan/task and all four separately owned kit-file hashes are preserved. No hub, member, SSH host or non-public service was contacted; no setup, install, credential read or Git write occurred.

### Checklist results

| Check | Result | Evidence |
|---|---|---|
| PR-6 | fail | No current correction census/map; explicit admission at :2709; no equivalent found in receipt inventory/text searches. |
| PR-1–PR-5, PR-7–PR-9 | n/a | Not reached under the mandatory pre-verdict gate; no substantive pass claimed. |
| DR-1–DR-8 | n/a | Not reached under the mandatory pre-verdict gate; input hash agreement is not correction approval. |
| Review scope preservation | pass | Only canonical review edited; previous body preserved byte-for-byte and protected file hashes unchanged. |

### Verdict and residual risk

**`changes_required`.** PR-6 must be satisfied or explicitly handled by the human before a protocol-compliant approval is possible. The two previous High findings are not independently closed, and correction-introduced defects have not been assessed. This final round ends at the human handback; there is no automatic ninth round or execution authorization.

The structured schema requires a severity field even for this procedural exception. F-036's `Low` is a transport placeholder only; the workflow's explicit PR-6 exception is the reason for withholding approval. No delivery-level severity is assigned to missing census evidence.

### Structured verdict

```json
{
  "schema_version": "review-verdict.v1",
  "date": "2026-11-14",
  "review_mode": "plan",
  "target_plan": "docs/execution/plans/2026-11-07-usb-kit-hardening",
  "agent": "Codex",
  "requested_verbosity": "detailed",
  "verdict": "changes_required",
  "summary": "Round 8 of 8: changes_required solely under the PR-6 procedural exception. F-036: the round-7 correction resubmission explicitly has no current blast-radius census or per-hit disposition map. The workflow prohibits substantive recheck in that condition; F-027 through F-035 remain independently unverified, including the two prior High blockers. No new delivery-level severity is assigned; Low is the schema transport placeholder. Final-round handback to the human; no execution or further round authorized. Record: .agent/context/handoffs/2026-11-07-usb-kit-hardening-plan-critical-review.md. 🕐 Completed: 2026-11-14 20:01 (EST)",
  "findings": [
    {
      "id": "F-036",
      "severity": "Low",
      "confidence": "High",
      "finding": "PR-6 procedural precondition failure: the current correction resubmission has no blast-radius census receipt and no per-hit disposition map. Low is a required schema placeholder, not a delivery-level severity or the reason approval is withheld.",
      "file_line": ".agent/context/handoffs/2026-11-07-usb-kit-hardening-plan-critical-review.md:2709; .agent/context/handoffs/2026-11-07-usb-kit-hardening-plan-critical-review.md:2681; core/.agent/workflows/plan-critical-review.md:256; core/.agent/workflows/plan-critical-review.md:287",
      "recommendation": "Hand back to the human at the eight-round cap. The missing evidence is an untruncated old/new and semantic-variant sweep of both plan files plus an updated/confirmed-consistent disposition for every file:line hit. Any further review or protocol exception requires human direction; do not execute on the basis of this round.",
      "status": "open"
    }
  ],
  "checklist_results": [
    {
      "check": "PR-1",
      "result": "n/a",
      "evidence": "Not reached: PR-6 expressly stops substantive review before this checklist assessment. No inherited pass is asserted."
    },
    {
      "check": "PR-2",
      "result": "n/a",
      "evidence": "Not reached: PR-6 expressly stops substantive review before this checklist assessment. No inherited pass is asserted."
    },
    {
      "check": "PR-3",
      "result": "n/a",
      "evidence": "Not reached: PR-6 expressly stops substantive review before this checklist assessment. No inherited pass is asserted."
    },
    {
      "check": "PR-4",
      "result": "n/a",
      "evidence": "Not reached: PR-6 expressly stops substantive review before this checklist assessment. No inherited pass is asserted."
    },
    {
      "check": "PR-5",
      "result": "n/a",
      "evidence": "Not reached: PR-6 expressly stops substantive review before this checklist assessment. No inherited pass is asserted."
    },
    {
      "check": "PR-6",
      "result": "fail",
      "evidence": "Correction log explicitly states no blast-radius census ran; no current per-hit map found in the correction section or receipts. Diffs and finding-level dispositions are present but do not satisfy PR-6."
    },
    {
      "check": "PR-7",
      "result": "n/a",
      "evidence": "Not reached: PR-6 expressly stops substantive review before this checklist assessment. No inherited pass is asserted."
    },
    {
      "check": "PR-8",
      "result": "n/a",
      "evidence": "Not reached: PR-6 expressly stops substantive review before this checklist assessment. No inherited pass is asserted."
    },
    {
      "check": "PR-9",
      "result": "n/a",
      "evidence": "Not reached: PR-6 expressly stops substantive review before this checklist assessment. No inherited pass is asserted."
    },
    {
      "check": "DR-1",
      "result": "n/a",
      "evidence": "Not reached: PR-6 expressly stops substantive review before this checklist assessment. No inherited pass is asserted."
    },
    {
      "check": "DR-2",
      "result": "n/a",
      "evidence": "Not reached: PR-6 expressly stops substantive review before this checklist assessment. No inherited pass is asserted."
    },
    {
      "check": "DR-3",
      "result": "n/a",
      "evidence": "Not reached: PR-6 expressly stops substantive review before this checklist assessment. No inherited pass is asserted."
    },
    {
      "check": "DR-4",
      "result": "n/a",
      "evidence": "Not reached: PR-6 expressly stops substantive review before this checklist assessment. No inherited pass is asserted."
    },
    {
      "check": "DR-5",
      "result": "n/a",
      "evidence": "Not reached: PR-6 expressly stops substantive review before this checklist assessment. No inherited pass is asserted."
    },
    {
      "check": "DR-6",
      "result": "n/a",
      "evidence": "Not reached: PR-6 expressly stops substantive review before this checklist assessment. No inherited pass is asserted."
    },
    {
      "check": "DR-7",
      "result": "n/a",
      "evidence": "Not reached: PR-6 expressly stops substantive review before this checklist assessment. No inherited pass is asserted."
    },
    {
      "check": "DR-8",
      "result": "n/a",
      "evidence": "Not reached: PR-6 expressly stops substantive review before this checklist assessment. No inherited pass is asserted."
    },
    {
      "check": "Review scope preservation",
      "result": "pass",
      "evidence": "Input hashes and independent full diffs captured; plan/task and four separately owned kit files unchanged; only canonical review edited in the repository, with scratch output in the authorized review-r8 folder."
    }
  ]
}
```

🕐 Completed: 2026-11-14 20:01 (EST)

## Census — 2026-11-14, round-7 corrections (input to round 9)

Round 8 refused to recheck, because the round-7 corrections had no blast-radius census (F-036, review:2734). On 2026-11-14 the human typed "add round 9". This pass records that direction and adds the census that PR-6 requires. It changes plan and task text only. It dispatches no review, makes no commit, and changes no code or kit file.

**Blast-radius census:** 216 values changed or swept (44 old, 115 new, 57 variants), 648 searches, 1122 sites found, 673 updated, 449 confirmed consistent, 339 zero-hit searches, 0 unresolved.

The 216 values are 207 values written by hand from the round-7 corrections and from this pass, and 9 values that the census script derived from the diff. Each value is searched in three texts: `final` (the plan folder after this pass), `r0` (the round-7 input, `corrections-r7/before`) and `kit` (the 12 existing kit files, read only).

| Class | Target | Searches | Hits | Updated | Confirmed consistent | Zero-hit |
|---|---|---|---|---|---|---|
| old | final | 44 | 7 | 5 | 2 | 40 |
| old | r0 | 44 | 41 | 39 | 2 | 6 |
| old | kit | 44 | 8 | 0 | 8 | 42 |
| new | final | 115 | 395 | 339 | 56 | 0 |
| new | r0 | 115 | 126 | 70 | 56 | 77 |
| new | kit | 115 | 25 | 0 | 25 | 106 |
| variant | final | 57 | 269 | 138 | 131 | 7 |
| variant | r0 | 57 | 213 | 82 | 131 | 13 |
| variant | kit | 57 | 38 | 0 | 38 | 48 |
| **Total** | | **648** | **1122** | **673** | **449** | **339** |

- Disposition: a final or r0 line that has an identical line in the other text is `confirmed-consistent`. Any other line is `updated`, and its reason names the round that changed it: round 7, or this pass. Every kit hit is `confirmed-consistent`, because no kit file changed; each reason says why the kit line agrees with the plan.
- The 7 old-value hits in the final text each have a reason. They are the test stub folder (plan:373), "No file goes in a world-writable temp folder" (plan:960), the AC-32 negative test for `$TMPDIR` and `/tmp` (plan:1012), the `/tmp`-style folder as a failing case (plan:222, plan:1534), and the `--red` mode (plan:1124).
- Every new value has at least one final hit. The 7 zero-hit variants show that an old phrase is gone.

The census found 7 real inconsistencies in the round-7 output. This pass fixed them in the plan and the task, and ran the census again:

1. plan:215-219: the Helper text ("The first line is `#!/bin/bash -p`" to "No other variable reaches a tool.") had moved under the Parent walk bullet. It is back in the Helper bullet; the Parent walk bullet follows at plan:220-223.
2. plan:225-226: the Mode reader user list now reads "The Helper, the Parent walk, the Drop-in snapshot and the Key-auth check all use it."
3. plan:1534: the A-19 reason said that a rerun with a new pin installs beside the old version. Step 1 and AC-32 leave an existing pwsh 7 or later as it is, so the two texts disagreed. The reason now matches step 6 (plan:966-969) and step 8 (plan:976-978).
4. task:57: row 8b now reads "the Parent walk before any download, stage, unpack, root run or link".
5. plan:559: AC-9 now says "after the Parent walk passes", with the defined term.
6. task:49: row 4 now says "check with the Parent walk and the Mode reader", with the defined term.
7. plan:1534: the first rewrite of fix 3 said "no half-installed tree", but step 6 replaces a folder that an earlier failed run left. The reason now reads "A versioned folder, filled through a .new stage and linked last, means a failed run leaves no link, and a rerun replaces any stage or version folder that it left, so a rerun starts clean."

The round-9 direction is recorded at plan:90-94 (Review limits: 9 plan rounds, the ninth added after round 8 with "add round 9"), plan:121-123 (round 8 refused on F-036; round 9 is the next review) and task:36.

| File | Before (round-7 output) | After (this pass) |
|---|---|---|
| `implementation-plan.md` | sha256 `2b003d730f4cce45e074e84a65f024b5618a32a27f69cd34323f31e1bc61fab3`, 1689 lines | sha256 `6237f948539d3dd340d6446c06b0e0d0d29af52b89a00e1e4355009329968974`, 1691 lines, LF |
| `task.md` | sha256 `651dd68482f25d1875678984953d86db39dbd7d8666825afa0de330d5b7784f9`, 110 lines | sha256 `aec562fc0ac52cfb55f44cee889f1df7b5c5e1adae06eec2a65752ec64602b8a`, 110 lines, LF |

Receipts (`receipts in C:/Temp/zorivest/usb-kit-plan/census-r7/`):

- `census-receipt.txt`: every search, its exit code and each matching line in full (2575 lines).
- `census-dispositions.md`: one row per receipt hit (file:line, term, disposition, reason), then one row per zero-hit search.
- `census-terms.txt`, `census-summary.txt`, `census-rows.tsv`, `read-list.txt`, `unresolved.txt` (empty) and `census-run5.txt` (the final run, exit 0).
- `before/` and `after/`: the plan and the task before and after this pass.
- `tools/`: the census, reason, verify and final-check scripts.

**Verification:** `census_verify_r7.py` passes (`census-verify.txt`: searches 648, receipt hits 1122, map rows 1122, zero-hit 339, zero-hit rows 339, updated 673, confirmed consistent 449). It checks the receipt and the map 1:1 in order, the cell count of each row, the dispositions, that no row is unread, the zero-hit rows and the summary line. `lint_task_contract.py` passes with 44 rows, 42 fully checked and 2 exempt (H1-5, H2-1) (`lint-task.txt`, exit 0). The seven static tests pass: 7 passed, 316 deselected (`pytest-static.txt`, exit 0). `final_checks_r7.py` (`final-checks.txt`) shows that the D-1, D-2 and D-3 records are byte-identical to the round-7 output and to the round-7 input (1956, 1277 and 1496 characters), and that the task stays parked with `status: "approved"` and `stop_gate: "released:human-gate"`.

**Open for the human (described, not decided):** step 1 leaves any pwsh 7 or later as it is, so a rerun never moves a member to a newer pin. The Out of Scope row "Removing older PowerShell version folders" assumes that older version folders exist. Whether the kit upgrades its own install when the pin changes is a scope question.

## Recheck (2026-11-14) — Round 9 of 9

Executing this plan should close the seven USB-kit gaps, preserve working administrative access and the approved trust boundaries, and install hash-checked PowerShell on new Linux and macOS members. The discovered-PowerShell privilege fix and the filesystem-parent fix are present, but the new root-tool execution boundary leaves a separate executable-selection attack open.

**Verdict: `changes_required`. F-037 (High) must be fixed before execution starts.** F-038 and F-039 are Low, nonblocking single-statement notes. PR-6 passes and F-036 is closed. This is the ninth and last authorized round, following the human's typed "add round 9"; the findings are the record for the human. No further review round, corrections, execution, commit or push is authorized by this verdict.

### Scope and method

`plan` below means `docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md`; `task` means the adjacent `task.md`. Read the requested round-7 review, round-7 corrections, round-8 review and final census section in that order. Read the complete current plan and task, including all 11 work packages, 25 Named definitions, 32 distinct ACs, 13 stop conditions and 44 task rows, and the current kit scripts, launch/prepare/import contracts, both separately owned READMEs, bootstrap security rules, relevant fleet lookup code and test/gate sources. Both before-to-current comparisons were generated independently, including removed text, rather than treating the corrections table as evidence of a fix.

The work is unstarted: all 44 task statuses are unchecked; the implementation handoff does not exist. The task's parked `approved`/`released:human-gate` metadata remains the historical parking state, not authorization to execute this amendment. The four dirty kit files belong to the other session and were read without alteration. The human's reading at the plan-to-execution gate is the terminating trust anchor; no defense against an author forging the plan is required or asserted.

### Findings — refutation before retention

| ID | Severity | Confidence | Blocking | Kind | Finding and concrete failure | Evidence | Recommendation | Status |
|---|---|---|---|---|---|---|---|---|
| F-037 | High | High | **yes** | behavior | The new Execution identity boundary assigns root to supporting tools but never binds their executable lookup to trusted system paths. A member whose sudo policy leaves an account-writable prefix on the setup's `PATH` can run an account-controlled `stat`, `sudo`, `tar` or hash tool as root. A fake `stat` can also report safe parents before the Parent walk accepts them. Protected download/install/link destinations do not protect the programs used to check or populate them. | `plan:220-226`, `:927-943`, `:952-977`, `:1012`; `task:57`; `.agent/fleet/usb/setup-unix.sh:9-19`, `:122-128` | Establish a trusted root-tool lookup at the production setup entrypoint before any external root command; resolve root tools from protected system directories, clear stale command lookup state, and keep account-shell discovery on the account side. Add an AC-32 negative through that entrypoint with hostile `PATH` entries for a measurement tool and an action tool. Do not fix this by taking ownership of package-manager directories. | open |
| F-038 | Low | High | no | clerical | The newly introduced release-page cap is restated as an operative number in the fetch algorithm, Probe-3, Boundary Inventory, AC-32, stop 13 and row 8b. They agree now; changing the cap at the named human gate can leave a checker or stop at the old cap. This is PR-9 maintenance drift, not a present selection ambiguity. | `plan:914-916`, `:987`, `:1002`, `:1012`, `:1219-1221`; `task:57` | Keep the numeric cap in WP-U6p step 1 and refer to that page limit elsewhere; retain boundary fixtures in terms of the limit. | open |
| F-039 | Low | High | no | clerical | The new Parent walk invariant is defined once and then restated in the PowerShell Boundary Inventory. Both spellings agree; a later change can make the named check and the row's owner/write-bit rule diverge. The correct governing definition is readily inferable. | `plan:220-223`, `:1006` | Have the row reference Parent walk, retaining its additional physical-path-equality and leaf-file requirements through steps 4, 7 and 8. | open |

**F-037, attempted refutation.** The exact F-027 sink is repaired: the login-shell discovery and each discovered `pwsh` version probe use `sudo -u "$user" -i`; no root `command -v pwsh` remains. The new archive binary has its hash and protected parent/leaf checks before root executes it. Neither fact constrains how the root shell finds its other executables. The actual setup has no `PATH` assignment. The plan's fixed `/usr/sbin:/usr/bin:/sbin:/bin`, absolute tools and `env -i` belong to the **Helper** (`plan:215-219`, `:227-232`, `:532-537`), whose own scoped sudoers setting cannot alter the already-running setup shell. A-18 examines the account's sudoers policy for the helper; it does not establish the setup shell's tool path. There is no production call chain to a root-tool resolution check before the new Mode reader/Parent walk or install actions.

[Bash's command-search contract](https://www.gnu.org/software/bash/manual/html_node/Command-Search-and-Execution.html) resolves unqualified external commands through `PATH` (and may reuse its command hash). The cited [upstream sudoers manual, `secure_path`](https://raw.githubusercontent.com/sudo-project/sudo/main/docs/sudoers.man.in) expressly describes the arbitrary-command risk when privileged scripts do not set a safe path or use fully qualified commands. A site may configure a safe sudo path; the plan neither requires nor verifies it for the setup. This finding does **not** assume that every stock distro or Mac has an unsafe sudo path. The supported counterexample is a member with an account-writable tool prefix on the root setup's effective path, which the new contract does not exclude. Homebrew's account-owned prefix is a real example of such a tool source ([ownership documentation](https://docs.brew.sh/FAQ#what-are-the-default-ownership-and-permissions-used-by-homebrew)); rejecting the separate install/bin destinations does not validate that source.

A harmless Git-bash probe executed only the literal planned `tar --no-same-owner -xzf "$archive" -C "$stage"` fragment and the Mode reader's `stat -c '%u %g %a'` fragment. With a scratch tool directory first on `PATH`, the fake tar's body printed its marker and exited 37; the fake stat printed its body marker and returned `0 0 755`, exit 0. With a fixed system path and cleared lookup cache, neither marker appeared. **No privilege transition or real setup ran.** The root consequence follows from `plan:927-939` specifying that caller identity; the probe proves executable selection, not live elevation.

This is a separate unprotected producer/action chain in the newly written Execution identity/Parent walk text, not a request for a deeper version-probe mutation: F-027's discovered interpreter now runs under the correct uid. F-028's specified physical ancestor/destination checks are also present. F-037 concerns the tools executing those checks/actions. It violates **PR-8's traceable production control requirement** and the hardening objective: the planned happy-path and stub tests can pass while account code executes with root privilege before any archive `pwsh` version check. A later nonzero tar exit does not undo that execution. This is the sole delivery-level blocker.

**F-038/F-039, attempted refutation and Materiality Gate.** All current numeric/invariant spellings agree. The plan names the relevant sources, and an intelligent reader can infer the governing rule; neither note demonstrates a current materially missing deliverable or different live behavior. PR-9 nevertheless asks that repeated thresholds/predicates have one definition. These two newly added clusters are recorded once each, at Low; neither contributes to withholding approval. They do not reopen F-033, whose release-selection predicate has been centralized successfully.

### PR-6 census audit — F-036 fixed

The census section at `review:2898-2948` names the raw receipt, the per-hit map and its verifier. In `census-r7/tools/census_r7.py`, `run_rg` invokes the real binary with `--no-config -F -n --no-heading --with-filename --color never -e <literal> -- <files>`, captures complete output and exit status, and writes every matching line. It does not head-truncate, select representative hits or substitute a count for the receipt. The searches include both plan files, the round-7 before copies and 12 read-only existing files; absent future artifacts are listed explicitly.

The 216 terms include old and new execution-identity wording, the old root discovery and new account-run forms, Parent walk and replaced helper-walk wording, physical paths, modes and redirects, old temp staging and new protected staging, PATH limitations, old/new page sizes and pagination/cap/foreign-host conditions, both tar forms, Probe-3 timing/import wording, old/new selection wording, generated-file retention, lifecycle strategy, relevant AC/stop/decision/count references, and the census pass's own corrections and round-9 grant. The changed/removed text in both full diffs is covered; no uncovered round-7 correction term or omitted hit was found.

An independent parser reconstructed **all 648 searches from the actual file lines**, checked full hit text, exits and zero-hit results, and matched the raw receipt to **1,122 disposition rows in order**, with **339 zero-hit rows**. Every hit has exactly one disposition per sweep/target/location, a reason and, where appropriate, a successor location. The totals are **673 updated and 449 confirmed-consistent**, with no reconstruction or disposition-classification mismatch. Repeated locations from different search terms are separate receipt hits, not duplicate dispositions for one hit. The supplied verify receipt reports the same figures and exit 0.

Read the disposition reasons against the cited current lines, removed lines/successors and existing source. Unchanged-line classification alone was not treated as proof of consistency. The seven old-term final hits are accounted for as a test-fixture folder, a prohibition, negative/failing `/tmp` cases or the unrelated `--red` timing. The census pass actually restores the Helper paragraph to its own bullet, adds Parent walk to the Mode reader users, corrects A-19's rerun explanation, includes download in row 8b's walk timing, capitalizes the two intended definition references and records round 9. Those edits agree with their dispositions. Minor reason labels referring to the Unix link stop as WP-U4 are readily inferable WP-U5 labels; their cited line and disposition remain correct and do not invalidate PR-6. **F-036 is closed; this verdict is substantive, not the procedural exception.**

Receipt names: `census-receipt.txt`, `census-dispositions.md`, `census-verify.txt` and the declared before copies under `census evidence in C:/Temp/zorivest/usb-kit-plan/census-r7/`. Independent comparisons and audit output are under `round-9 evidence in C:/Temp/zorivest/usb-kit-plan/review-r9/`. These are working receipts; the decisive results are preserved here.

### F-027 through F-035 — current-text recheck

| Finding | Result | Current text and conclusion |
|---|---|---|
| F-027 | fixed, exact discovered-`pwsh` defect | `plan:931-946`, `:1005`, `:1012`, `:1203-1207`, `:1530-1534`; `task:57`. The root shell calls system sudo; the account's login shell executes discovery; each discovered executable runs as that account. The `<bin dir>/pwsh` existence check executes no binary. Failed/older existing versions stop. The identity negative requires the account route and forbids a root marker. The supporting system-sudo/tool lookup itself is the distinct F-037 gap above. |
| F-028 | fixed, specified ancestor/destination defect | `plan:220-226`, `:952-978`, `:1006`, `:1012`, `:1200-1208`; `task:57`. Before writes, walk the install root (or deepest existing ancestor) and bin parent physically; create only missing protected folders, then recheck. Download is under `.dl-<pid>`; staging is `<version>.new`; both inherit the protected root. Recheck the final version folder before execution, require a regular non-symlink root-owned non-writable `pwsh`, and walk the bin parent again before publication. Owner/write-bit/sticky/redirect negatives and named stop 6 exist. A package-manager-owned bin dir is refused, never chowned into compliance. F-037 prevents unconditional certification of the tools producing these observations; it does not erase these textual fixes. |
| F-029 | fixed | `plan:192-193`, `:989-995`, `:1108-1113`, `:1176-1177`, `:1240`; `task:62-63`. Absolute fallback proves installation only. The member process must find `pwsh` in its own environment; later Unix provisioning owns that check. Real fleet lookups at `fleet.py:1466`, `:1641-1643`, `:1788-1789` confirm the limitation. No excluded Unix bootstrap work is demanded. |
| F-030 | fixed | `plan:911-923`, `:1002`, `:1012`, `:1022`, `:1219-1221`; `task:57`. Follow every next page, choose only after a complete bounded list, stop at page 10 with next remaining or a foreign-host next URL, and write nothing on refusal. A page-2-winning fixture and cap/foreign-host fixtures are explicitly scheduled in AC-32 and row 8b. As this is an unstarted plan, those tests do not yet exist as implemented code. |
| F-031 | fixed | `plan:967`, `:1530` use `tar --no-same-owner -xzf "$archive" -C "$stage"`; `-f` now receives the archive. GNU tar and Apple's bsdtar primary option documentation support the corrected form. |
| F-032 | fixed | `plan:983-987`, `:1104-1108`; `task:44`, `:57`. Probe-3 follows the pure helpers and passing AC-32 tests, before drive/member writes. Mode-specific imports are deferred, so the baseline's other modes and selftest can run first. |
| F-033 | fixed | `plan:406-408`, `:918-923`, `:1001`, `:1012`, `:1545-1554`. A-21 is the canonical release-selection predicate; operative algorithm/AC references name it. The human's quotation and fixture examples are not competing predicates. F-038 concerns the different, newly introduced pagination bound. |
| F-034 | fixed | `plan:1062-1068`; `task:58` include `pwsh-pin.txt` among prepare's overwritten generated files and preserve the not-a-reset warning. |
| F-035 | fixed | `plan:74`; `task:57` both use `compact_continue` with the matching reread list. |

The root-side programs named or implied by this step are sudo, main's uname calls, the Mode reader's stat, install, rm, curl, the platform hash tool, tar, ownership/mode normalization, mv and ln, followed by the newly checked absolute `pwsh`. They run in the setup's root context; shell file tests and pin-parser builtins add no executable privilege transition. Discovered login-shell/PowerShell execution is account-side. The final binary's bytes and location are protected by the new contract; root utility provenance is not. Accordingly, **the requested unconditional statement that no account-controlled executable can run as root cannot be confirmed** until F-037 is resolved.

### Changed text, regression and complete coverage

| Scope | Verification/result |
|---|---|
| Both required comparisons | Round-7-before to current: plan 22 unified-diff hunks, task 3. Pre-census to current: plan 5 hunks, task 3. Full diffs retained; every changed definition, step, AC, negative, stop, inventory/task row and validation was read as new text. |
| Human decisions | D-1, D-2 and D-3 Decision Log records are byte-identical across the round-7 input, pre-census input and current plan: 1,956, 1,277 and 1,496 characters respectively. All remain ruled A. The D-1 brief's changed parent-path explanation now references Parent walk without changing the ruling or access grant; D-2's brief is unchanged. |
| Review grant | `plan:90-94`, `:120-123`; `task:36` record 9 rounds and the exact quote "add round 9". No new execution or commit grant is inferred. |
| AC preservation | Exactly 32 unique IDs, AC-1 through AC-32, matching `AC_COUNT`. AC-14 and AC-27 intentionally have separate OS halves. Relative to round-7 input, only AC-9, AC-24, AC-25 and AC-32 change: the named-walk reference, evidence limits and new security/pagination cases. All other AC rows are text-identical. |
| Stops | Exactly stops 1–13. Only 6 and 13 changed, adding the specified setup/path/identity and pagination refusals. Record retirement, password/key checks, fingerprint/pin refusal, privacy, dependency, review and human gates keep their meaning. |
| Dependencies and task contract | All 11 WP nodes and 44 task nodes resolve and are acyclic. U6p follows U6 and precedes U7; row 8b follows 8a and precedes 9. All AC, WP and A-1–A-21 references resolve. Task lint passes 42 command rows plus 2 source-read exemptions. All inline Python validation snippets parse. |
| Artifact existence | Validation scripts, templates, schemas and existing regression tests exist, or their creation is explicitly scheduled. Future kit helper/tests/checkers/handoff/reflection paths are not falsely represented as current code. No missing unscheduled executable was found. |
| Named definitions | All 25 read: Kit; Drive folder; Helper; Parent walk; Mode reader; Sudoers file; Drop-in; Marked block; Key-auth check; Password-off check; Record retire; Listener check; Firewalld rules; Firewalld checks; SSH rule report; Member subnets; Load guard; Git bash; Stub folder; Admin check; Outcomes; Probe; Console guard; PowerShell pin; PowerShell step. The extracted Helper content retains its interpreter/environment protection; F-037 concerns the separate setup context. |
| AC-1–AC-13 | Constants/scans/update order; library/load/static/encoding/privacy guards; characterization; Git-bash location; helper/sudoers/environment/outcomes and Windows active-store firewall reporting retain their production callers and negatives. No prior fixed finding reopened. |
| AC-14–AC-21, AC-26–AC-28, AC-31 | Console guards; subnet/firewalld/listener/key order; rollback; record retire/name clash; hub password probe; image/CLI checks; docs/drive trust; sudo environment; fingerprint/pin refusal retain their meaning. D-1's configured-package residual and D-2's installer-before-check exposure remain disclosed. |
| AC-22–AC-25, AC-29–AC-30, AC-32 | Package/live coverage, privacy and input-identity controls remain bound to their task rows and producers. New PATH evidence limitations are explicit. New root utility provenance gap is F-037; cap and invariant restatements are F-038/F-039. No live AC is claimed executed. |
| Exclusions/security canon | Existing Unix bootstrap exclusion is real (`test_fleet_bootstrap.py:247-250`). No new GitHub credential, sign-in, secret file or inbound port is introduced by PowerShell. Hub metadata fetch is unauthenticated. The already-scoped SSH-kit port-22 exception remains the prior approved work; fleet members open no fleet listener. Password/key/drive and no-secret-in-evidence rules are retained. |
| Usability/complexity | Homebrew refusal is explicit with an account-install remedy; older/broken existing pwsh stops; missing OS/dependencies stop without a success record. Existing 7+ installs deliberately do not upgrade when the pin changes. The older-version-folder exclusion does not require an upgrade feature; no new human design decision is manufactured from that census observation. |

Primary-source recheck: unauthenticated public GitHub metadata yielded **three complete pages (100, 100, 29 releases)**. Applying the stated rules at `2026-11-14T00:00:00Z` yields **7.6.9**, published `2026-10-25T17:26:05Z`; all four asset digests match their notes' hashes. The [GitHub pagination documentation](https://docs.github.com/en/rest/using-the-rest-api/using-pagination-in-the-rest-api) and [release API documentation](https://docs.github.com/en/rest/releases/releases) support following next links and `per_page=100`. This is an independent read-only metadata check, not execution of future `fetch_releases`/Probe-3 code. Microsoft's [Linux archive guidance](https://learn.microsoft.com/en-us/powershell/scripting/install/alternate-install-methods) and [macOS archive guidance](https://learn.microsoft.com/en-us/powershell/scripting/install/install-powershell-on-macos) support the chosen transport/locations; they do not establish trust in a member's ambient executable path. The attempted Apple sudoers-source fetch returned HTTP 404; no claim about a particular stock Apple sudo policy depends on it.

### Executed evidence

Receipts and scripts are under `review evidence in C:/Temp/zorivest/usb-kit-plan/review-r9/`. Exact shell commands used the unfiltered `rtk proxy` route. The following decisive observations remain interpretable without those receipts.

```json
{
  "schema_version": "evidence.v1",
  "check_id": "r9-input-census-contract-audit",
  "command": "rtk proxy python -X utf8 -B C:/Temp/zorivest/usb-kit-plan/review-r9/audit.py",
  "cwd": ".",
  "scope": "Both before/current diffs, raw census reconstruction, map identity/classification, decisions, counts and dependency graphs",
  "phase": "static",
  "exit_code": 0,
  "result": "pass",
  "tested_state": "plan sha256 6237f948539d3dd340d6446c06b0e0d0d29af52b89a00e1e4355009329968974; task sha256 aec562fc0ac52cfb55f44cee889f1df7b5c5e1adae06eec2a65752ec64602b8a",
  "output": "648 searches; 1122 hits; 1122 map rows; 339 zero-hit rows; errors []; D-1/D-2/D-3 records byte-identical; 32 AC IDs; 25 definitions; 11 WP and 44 task nodes acyclic; both plan YAML blocks parse. The audit's first run had a reviewer-parser assertion error, corrected before this successful run; no candidate defect was inferred from that error."
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "r9-task-lint",
  "command": "rtk proxy python -X utf8 -B core/tools/lint_task_contract.py --task docs/execution/plans/2026-11-07-usb-kit-hardening/task.md",
  "cwd": ".",
  "scope": "Current task contract",
  "phase": "static",
  "exit_code": 0,
  "result": "pass",
  "tested_state": "task sha256 aec562fc0ac52cfb55f44cee889f1df7b5c5e1adae06eec2a65752ec64602b8a",
  "output": "OK: 44 rows; 42 fully checked; 2 view_file exemptions H1-5 and H2-1; dependencies resolve and are acyclic."
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "r9-existing-security-static-tests",
  "command": "rtk proxy python -X utf8 -B -m pytest scripts/tests/test_fleet_bootstrap.py scripts/tests/test_fleet_agent.py -q -p no:cacheprovider --basetemp=C:/Temp/zorivest/usb-kit-plan/review-r9/pytest-temp -k \"(test_ac19_the and not effort) or test_ac32_forbidden\"",
  "cwd": ".",
  "scope": "Existing bootstrap template/deletion checks and unchanged forbidden-command set",
  "phase": "targeted",
  "exit_code": 0,
  "result": "pass",
  "tested_state": "Existing working-tree tests and bootstrap/fleet source; no implementation changes made",
  "output": "7 passed, 316 deselected in 0.34s"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "r9-inert-root-tool-selection-counterexample",
  "command": "rtk proxy python -X utf8 -B C:/Temp/zorivest/usb-kit-plan/review-r9/tool_resolution_probe.py",
  "cwd": ".",
  "scope": "Inert planned shell fragments under a synthetic tool path, then a fixed system path; no setup or elevation",
  "phase": "targeted",
  "exit_code": 0,
  "result": "pass",
  "tested_state": "Literal plan tar/stat fragments; scratch marker programs; installed Git bash",
  "output": "raw-tar exit 37 marker True; raw-stat exit 0 marker True and stdout 0 0 755; fixed-path-tar exit 0 marker False; fixed-path-stat exit 0 marker False. Probe assertions pass and demonstrate F-037's lookup failure; no root execution was performed."
}
```

Also executed the read-only `contracts.py` inventory/inline-Python parser (exit 0), public-source/metadata `source_probe.py` (exit 0, individual HTTP 404 explicitly disclosed above), file reads and read-only git/rg inspections. No setup/launcher, hub/member/run command, prepare/import, SSH connection, sudo, real install, credential/key/token-file read or Git write was performed. No future tests, full package gate, Pester suite or live member result is claimed.

### Checklist results

| Check | Result | Evidence |
|---|---|---|
| PR-1 | pass | Full plan/task alignment and both diffs read; 11 WPs and 44 task rows resolve. |
| PR-2 | pass | All statuses unchecked; implementation handoff absent; unrelated dirty kit files preserved. |
| PR-3 | pass | Task lint exit 0; all required columns, receipts, exits and dependencies pass. |
| PR-4 | partial | Commands/artifacts are executable or explicitly scheduled; root-tool hostile-path oracle is absent (F-037). |
| PR-5 | pass | Human A rulings unchanged; changed behavior traced to existing canon and cited primary sources. |
| PR-6 | pass | All 648 raw searches reconstructed; every hit/zero has its map row; reasons checked; F-036 fixed. |
| PR-7 | pass | Exclusions remain evidenced; later Unix member PATH work is explicitly outside this plan. |
| PR-8 | fail | New root measurement/action tools have no trusted executable-resolution producer (F-037). |
| PR-9 | partial | A-21 centralized; two new agreeing restatement clusters are nonblocking F-038/F-039. |
| DR-1 | pass | Current source and unchanged protected inputs support an unstarted plan, not completed implementation. |
| DR-2 | pass | Replaced values checked across both diffs/census; remaining old-value hits are explained negatives/history/unrelated uses. |
| DR-3 | pass | Changed definitions, inventories, task outputs and future-artifact references resolve. |
| DR-4 | partial | New owner/redirect/pagination/uid negatives are specified; root-tool lookup negative missing (F-037). |
| DR-5 | pass | Full diffs, independently reconstructed receipt/map, source snapshots and decisive command results preserved. |
| DR-6 | partial | Specified fixes agree across plan/task; F-037 prevents the global root-execution trust conclusion. |
| DR-7 | pass | Current hashes, decisions, census totals, AC/definition/task counts and metadata selection independently reproduced. |
| DR-8 | pass | Accepted residuals and unexecuted checks explicit; no execution-complete claim. |
| Review scope preservation | pass | Only the rolling review changed in the repository; previous text preserved except frontmatter round/verdict/count fields; six protected input hashes unchanged. |

### Verdict and human handback

**`changes_required`: F-037 must be fixed before execution begins.** F-027 through F-035's specific corrections and F-036's census precondition are verified above; they are not silently carried forward as unresolved. F-038/F-039 are clerical notes and cannot independently withhold approval. The unresolved issue is the separate privileged utility lookup, not a new governance choice, author-forgery defense or demand for unplanned Unix fleet provisioning.

The final-round record goes to the human. The accepted writable-drive/code trust limit, first-import fingerprint comparison, D-1's configured-package root residual, full Windows administrator, D-2's installer-before-check exposure, unsupported-platform/dependency stops, existing-version retention and lack of Unix member provisioning remain explicit. The workflow stops here.

### Structured verdict — Round 9

```json
{
  "schema_version": "review-verdict.v1",
  "date": "2026-11-14",
  "review_mode": "plan",
  "target_plan": "docs/execution/plans/2026-11-07-usb-kit-hardening",
  "agent": "Codex",
  "requested_verbosity": "detailed",
  "verdict": "changes_required",
  "summary": "Round 9 of 9: changes_required. F-037 (High) must be fixed before execution: root supporting-tool lookup remains exposed to an account-controlled PATH. F-027 through F-035 specific fixes verified; PR-6 passes and F-036 is closed. F-038/F-039 are nonblocking Low single-statement notes. Final-round handback to the human. Review: .agent/context/handoffs/2026-11-07-usb-kit-hardening-plan-critical-review.md.",
  "findings": [
    {
      "id": "F-037",
      "severity": "High",
      "confidence": "High",
      "finding": "Root supporting tools have no trusted executable lookup. An account-writable prefix on the setup PATH can supply stat/tar/hash tools executed as root; a fake stat can also fabricate safe-parent observations. The discovered-pwsh uid defect itself is fixed.",
      "file_line": "docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:224; docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:931; docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:936; docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:952; docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:1012; docs/execution/plans/2026-11-07-usb-kit-hardening/task.md:57; .agent/fleet/usb/setup-unix.sh:9",
      "recommendation": "Before execution, bind every root supporting executable to trusted system paths at the production setup entrypoint, clear stale lookup state, and add hostile-PATH measurement/action negatives through that entrypoint. Keep account discovery under the account uid.",
      "status": "open"
    },
    {
      "id": "F-038",
      "severity": "Low",
      "confidence": "High",
      "finding": "The new agreeing release-page cap is restated across algorithm, probe, inventory, AC, stop and task text, risking maintenance drift under PR-9. Nonblocking clerical note.",
      "file_line": "docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:914; docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:987; docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:1002; docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:1012; docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:1219; docs/execution/plans/2026-11-07-usb-kit-hardening/task.md:57",
      "recommendation": "Keep the numeric cap in WP-U6p step 1 and reference that page limit elsewhere.",
      "status": "open"
    },
    {
      "id": "F-039",
      "severity": "Low",
      "confidence": "High",
      "finding": "The new Parent walk owner/write-bit invariant is restated in the PowerShell Boundary Inventory. Spellings agree; this is nonblocking PR-9 maintenance drift.",
      "file_line": "docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:220; docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md:1006",
      "recommendation": "Reference Parent walk in the inventory while retaining references to the additional physical-path-equality and leaf-file requirements.",
      "status": "open"
    }
  ],
  "checklist_results": [
    {
      "check": "PR-1",
      "result": "pass",
      "evidence": "Full plan/task alignment and both diffs read; 11 WPs and 44 task rows resolve."
    },
    {
      "check": "PR-2",
      "result": "pass",
      "evidence": "All statuses unchecked; implementation handoff absent; unrelated dirty kit files preserved."
    },
    {
      "check": "PR-3",
      "result": "pass",
      "evidence": "Task lint exit 0; all required columns, receipts, exits and dependencies pass."
    },
    {
      "check": "PR-4",
      "result": "partial",
      "evidence": "Commands/artifacts are executable or explicitly scheduled; root-tool hostile-path oracle is absent (F-037)."
    },
    {
      "check": "PR-5",
      "result": "pass",
      "evidence": "Human A rulings unchanged; changed behavior traced to existing canon and cited primary sources."
    },
    {
      "check": "PR-6",
      "result": "pass",
      "evidence": "All 648 raw searches reconstructed; every hit/zero has its map row; reasons checked; F-036 fixed."
    },
    {
      "check": "PR-7",
      "result": "pass",
      "evidence": "Exclusions remain evidenced; later Unix member PATH work is explicitly outside this plan."
    },
    {
      "check": "PR-8",
      "result": "fail",
      "evidence": "New root measurement/action tools have no trusted executable-resolution producer (F-037)."
    },
    {
      "check": "PR-9",
      "result": "partial",
      "evidence": "A-21 centralized; two new agreeing restatement clusters are nonblocking F-038/F-039."
    },
    {
      "check": "DR-1",
      "result": "pass",
      "evidence": "Current source and unchanged protected inputs support an unstarted plan, not completed implementation."
    },
    {
      "check": "DR-2",
      "result": "pass",
      "evidence": "Replaced values checked across both diffs/census; remaining old-value hits are explained negatives/history/unrelated uses."
    },
    {
      "check": "DR-3",
      "result": "pass",
      "evidence": "Changed definitions, inventories, task outputs and future-artifact references resolve."
    },
    {
      "check": "DR-4",
      "result": "partial",
      "evidence": "New owner/redirect/pagination/uid negatives are specified; root-tool lookup negative missing (F-037)."
    },
    {
      "check": "DR-5",
      "result": "pass",
      "evidence": "Full diffs, independently reconstructed receipt/map, source snapshots and decisive command results preserved."
    },
    {
      "check": "DR-6",
      "result": "partial",
      "evidence": "Specified fixes agree across plan/task; F-037 prevents the global root-execution trust conclusion."
    },
    {
      "check": "DR-7",
      "result": "pass",
      "evidence": "Current hashes, decisions, census totals, AC/definition/task counts and metadata selection independently reproduced."
    },
    {
      "check": "DR-8",
      "result": "pass",
      "evidence": "Accepted residuals and unexecuted checks explicit; no execution-complete claim."
    },
    {
      "check": "Review scope preservation",
      "result": "pass",
      "evidence": "Only the rolling review changed in the repository; previous text preserved except frontmatter round/verdict/count fields; six protected input hashes unchanged."
    }
  ]
}
```

## Corrections Applied — 2026-11-14, round 9 (input to round 10)

Applied by the plan's author. This section is not an approval. All earlier text in this file is unchanged, the frontmatter included; only an independent reviewer can set `approved`. This pass changes plan and task text only. It dispatches no review, makes no commit, and changes no code, kit, test or doc file.

Direction in this pass:

- **Human direction.** On 2026-11-14, after round 9, the human typed "fix and add round 10". The plan loop gets a tenth round, and round 10 is the next review (plan:90-95, :124-126; task:36). The token budget stays 10,500,000.
- **D-1, D-2 and D-3 stay ruled A.** Their Decision Log records are byte-identical to the round-9 input and to the round-7 input (1956, 1277 and 1496 characters, `final-checks.txt`).
- **Task parked.** `status: "approved"` and `stop_gate: "released:human-gate"` are unchanged; the task frontmatter is byte-identical.

Each finding was checked against the cited plan lines and held; none is dismissed. Line numbers are for the final files: `plan` is `implementation-plan.md` and `task` is `task.md`.

| Item | Disposition | Correction | Where |
|---|---|---|---|
| F-037 (High) | fixed | New Named definition **Root tool path**, the one place that states the folder list `/usr/sbin:/usr/bin:/sbin:/bin`. It holds three parts. (1) The **clean start**: while `FLEET_USB_CLEAN` is not 1, `main` re-executes the file with `exec /usr/bin/env -i FLEET_USB_CLEAN=1 PATH=<Root tool path> LC_ALL=C TERM=dumb ... /bin/bash -p <file>`, with an allow-list for the Git bash names only when `OSTYPE` is `msys*` or `cygwin*`; after the re-exec it requires `p` in `$-` and checks each name from `compgen -e` against the allow-list, so a forged marker stops. Under `-p`, bash reads no `BASH_ENV` or `ENV` file, imports no function, and ignores `SHELLOPTS`, `BASHOPTS`, `CDPATH` and `GLOBIGNORE`. (2) The **Root tool check** `check_root_tools <Root tool path> <name>...` runs before any other external command: each name of the constant `root_tools` must resolve to a file in a folder of the Root tool path. The floor of `root_tools` is stated once (plan:256). The check runs again after WP-U5 step 3 installs a package. (3) The **launch form** `/usr/bin/sudo /bin/bash -p <setup-unix.sh>`, used in `Setup Mac.command:5`, `Setup Linux.desktop:7`, the `setup-unix.sh:6-7` header and the `usb/README.md:57-58` run lines. A typed bare `sudo bash setup-unix.sh` still reaches the clean start. New decision A-22 (with sources for sudo's `secure_path` and bash privileged mode); new User Review Required item 13 (two more kit files: 21 to 23 tracked, 6 to 8 changed kit and fleet files); WP-U5 intro and step 3; WP-U6p clean start sketch with a bash fragment (`bash -n` exit 0); Execution identity, Boundary, Spec Sufficiency and Files rows; AC-26 (a static test finds the Root tool path in the helper's `main`), AC-21 (a bare `sudo bash` in the README run lines fails) and AC-32 (a hostile `PATH` folder first, exported functions, a `BASH_ENV` marker script under the launch form, a forged marker with and without `-p`, a copy with its own `stat` function, copies without the clean start, and a static check for the launch form and no bare `sudo bash` in both launchers and the header comment); stop 6 names a clean start or Root tool check failure; the compaction re-read list reaches A-22. | plan:74, :163-167, :226-227, :235-267, :270-271, :604, :702-711, :984-985, :1031-1081, :1105-1106, :1112, :1122-1133, :1183-1200, :1306-1315, :1662-1676, :1757-1758; task:14, :57 (row 8b), :58 (row 9) |
| F-038 (Low) | fixed | WP-U6p step 1 is the one place that states the limit: `RELEASE_PAGE_LIMIT = 10`, "the page limit", a constant in `fleet_usb.py`. Step 1's stop text, Probe-3, the `Link` header Boundary row, AC-32, the Spec Sufficiency row, the Files row and stop 13 say "the page limit of WP-U6p step 1" and state no number. AC-32 reads the constant and holds no literal. | plan:959-963, :1086, :1101, :1112, :1122, :1130, :1326-1328; task:57 |
| F-039 (Low) | fixed | The PowerShell Boundary row now points to the Parent walk definition and restates no owner or mode rule; its failure cell names a failed Parent walk. The regular-root-file check stays in step 7. | plan:1105 |

**Blast-radius census (PR-6):** 68 values changed or swept (16 old, 29 new, 23 variants), 204 searches, 447 sites found, 337 updated, 110 confirmed consistent, 114 zero-hit searches, 0 unresolved. Each value is searched in three texts: `final` (the plan folder after this pass), `r0` (the round-9 input, `corrections-r9/before`) and `kit` (the 8 kit files that this plan changes or that F-037 names, read only).

| Class | Target | Searches | Hits | Updated | Confirmed consistent | Zero-hit |
|---|---|---|---|---|---|---|
| old | final | 16 | 1 | 0 | 1 | 15 |
| old | r0 | 16 | 24 | 23 | 1 | 1 |
| old | kit | 16 | 0 | 0 | 0 | 16 |
| new | final | 29 | 176 | 172 | 4 | 0 |
| new | r0 | 29 | 6 | 2 | 4 | 25 |
| new | kit | 29 | 4 | 0 | 4 | 27 |
| variant | final | 23 | 138 | 96 | 42 | 3 |
| variant | r0 | 23 | 86 | 44 | 42 | 6 |
| variant | kit | 23 | 12 | 0 | 12 | 21 |
| **Total** | | **204** | **447** | **337** | **110** | **114** |

- The one old-value hit in the final text is task:49, row 4 (the helper) "with the Parent walk and the Mode reader". It is confirmed consistent: it names the two definitions and restates no rule. F-039 was the PowerShell Boundary row.
- The kit hits for a bare `sudo bash` are `Setup Mac.command:5`, `Setup Linux.desktop:7`, `setup-unix.sh:6-7` and `usb/README.md:57-58`. Each is a change target of row 8b or row 9, and AC-32 or AC-21 fails if it stays. The kit files were read only; four of them carry another session's uncommitted work.
- The page-limit, folder-list and floor greps of `final_checks_r9.py` show that `10 pages`, `page 10` and `at most 10` have no hit outside step 1, the folder list is at plan:235 (the definition) and plan:270 (the sudoers line's own text, which plan:271 names as the Root tool path) only, and the `root_tools` floor is at plan:256 only.

The census found 2 real issues in the first output of this pass. This pass fixed them and ran the census again:

1. plan:1306-1315: the extended stop 6 was one line longer than 120 characters. It is rewrapped; the words are unchanged.
2. plan:1112: AC-32 cited `setup-unix.sh:15` as a fixed line. Row 8b moves that line, so AC-32 now reads "the run ends at the root check (`setup-unix.sh:15` today) with "run it with sudo"".

| File | Before (round-9 input) | After (this pass) |
|---|---|---|
| `implementation-plan.md` | sha256 `6237f948539d3dd340d6446c06b0e0d0d29af52b89a00e1e4355009329968974`, 1691 lines | sha256 `c55bcae167acc971fb9c64e8ee0d25ccdec7630f85b15b616f35f5d4d350b0cc`, 1809 lines, LF |
| `task.md` | sha256 `aec562fc0ac52cfb55f44cee889f1df7b5c5e1adae06eec2a65752ec64602b8a`, 110 lines | sha256 `0561afd386a33281fcc37d11a0ab04a66a82f5439b25e3c37fd1ff5c8ace11d3`, 110 lines, LF (lines 14, 36, 57 and 58 changed) |

Counts after this pass: 26 Named definitions (25 before), `AC_COUNT` 32 (no new AC), 44 task rows, 25 Decision Log entries (A-1 to A-22, D-1 to D-3), 13 stop conditions.

Receipts (`receipts in C:/Temp/zorivest/usb-kit-plan/corrections-r9/`):

- `census-receipt.txt`: every search, its exit code and each matching line in full (833 lines).
- `census-dispositions.md`: one row per receipt hit (file:line, term, disposition, reason), then one row per zero-hit search.
- `census-terms.txt`, `census-reasons.txt`, `census-rows.tsv`, `census-summary.txt` and `census-run3.txt` (the final run, exit 0).
- `before/` and `after/`: the plan and the task before and after this pass; `plan-diff.txt` and `task-diff.txt`.
- `tools/`: the census, verify and final-check scripts, and this section.

**Verification:**

- `census_verify_r9.py` passes (`census-verify.txt`: searches 204, receipt hits 447, map rows 447, zero-hit 114, zero-hit rows 114, updated 337, confirmed consistent 110; exit 0).
- `lint_task_contract.py` passes with 44 rows, 42 fully checked and 2 exempt (H1-5, H2-1) (`lint-task.txt`, exit 0).
- The seven static tests pass: 7 passed, 316 deselected (`pytest-static.txt`, exit 0).
- `final_checks_r9.py` passes (`final-checks.txt`, exit 0): the hashes and line counts above, D-1 to D-3 identity, the parked frontmatter, the counts above and the one-definition greps.
- `bash -n` on the plan's clean start fragment (plan:1038-1075) exits 0 (`bash-n.txt`).
- No AC was executed, because every correction is plan text and the code does not exist yet.

Residual risks:

- Rows 13 and 14 must show on real members that `env -i /bin/bash -p` works on macOS bash 3.2 and that its `compgen -e` names match the allow-list.
- `root_tools` must name every external command that runs as root. The static check asserts only the floor names.
- 10 plan rounds share the unchanged 10,500,000-token budget.

**Open for the human (described, not decided):**

- The launch form adds two kit files (`Setup Mac.command`, `Setup Linux.desktop`), so the scope grows from 21 to 23 tracked files (User Review Required item 13).
- The plan-corrections workflow asks the author to change the frontmatter verdict. The brief for this pass forbids any frontmatter edit. This pass follows the brief and left the frontmatter as it was.

🕐 Completed: 2026-11-14 (EST)

## Recheck (2026-11-14) — Round 10 of 10

Executing this plan should close the seven USB-kit gaps, preserve working administrative access and the human-approved trust boundaries, and install hash-checked PowerShell on new Linux and macOS members. The current plan and task specify the controls and runnable checks needed to deliver that objective.

**Verdict: `approved`. No new findings; nothing remains that must be fixed before execution starts.** F-037, F-038 and F-039 are fixed. F-027 through F-035 remain fixed and F-036 stays closed. This is the tenth and last authorized plan-review round, following the human's typed **"fix and add round 10"**. Approval is of the plan; execution still waits for the human's proceed instruction and row 0.

### Scope, state and findings

`plan` below means `docs/execution/plans/2026-11-07-usb-kit-hardening/implementation-plan.md`; `task` is its adjacent `task.md`. Read both completely, round 9 and the appended round-9 corrections, both before/current diffs, all census terms and disposition reasons, and the cited current kit/launcher/bootstrap/fleet and peer-checker sources. Coverage includes all 11 work packages, 26 Named definitions, 32 distinct ACs (34 rows because AC-14 and AC-27 have OS halves), 13 stop conditions and 44 task rows, including every validation cell.

There are **no new supported findings** and no surviving correction notes. F-040 is therefore unused. Candidate concerns were checked against the actual call chain, the governing definitions and primary documentation before this conclusion. The human reading at the plan-to-execution gate remains the terminating trust anchor; this review does not demand protection from an author forging their own evidence.

The plan remains unstarted: every task status is unchecked and the project implementation handoff is absent. The task's unchanged `approved` / `released:human-gate` frontmatter is its historical parked state. The four separately owned dirty kit files were read and their diffs inspected, never edited. Only this rolling review was changed in the repository.

### PR-6 — independently reconstructed census

The corrections section names `census-receipt.txt`, `census-dispositions.md` and `census-verify.txt`, under `correction evidence in C:/Temp/zorivest/usb-kit-plan/corrections-r9/`. The supplied census producer was read: it runs `rg --no-config -F -n --with-filename -- <literal> <files>`, captures the complete stdout and status, and stores every matching line. Its metadata headings and zero-hit records do not replace or filter the matching output. No truncation or representative-hit selection was found.

The 68 declared terms cover the three corrections and the review extension: old/new page-count forms and the named page limit; the removed Parent-walk invariant and its replacement references; the Root tool path, clean start, Root tool check, launch form, function/marker names, startup-variable and lookup variants, root-tool list, affected launchers/header/README lines, scope counts, changed decision/reread references and the exact round-10 grant. The sweep covers both current plan files, both round-9 input copies and all eight declared read-only kit files. Reading the full diffs found no uncovered correction cluster.

Independently re-ran **all 204 searches** and compared every full matching line, exit code and zero-hit result with the raw receipt. The result is **447 hits, 447 per-hit dispositions, 114 zero-hit records, 337 updated and 110 confirmed-consistent**. Each receipt hit has exactly one map row in receipt order, with the same term, target and `file:line`, a permitted disposition, a reason and a valid successor location where given. Matching the before/current line pairs independently confirms the updated/unchanged classification. Read the reasons against the cited current lines, removed lines and their successors; unchanged classification alone was not treated as proof of consistency.

Independent `rg` runs can enumerate different files in a different thread order. The raw-line comparison preserves multiplicity and compares the complete hit sets; map ordering is checked against the submitted receipt's own order. An initial reviewer-audit failure caused solely by assuming stable cross-file enumeration was corrected; it was not a candidate defect.

The sole old-term hit in the current text, `task:49`, names the Parent walk and Mode reader for the helper without restating their rule. Existing bare-launcher hits identify the exact changes scheduled by row 8b and row 9; AC-32/AC-21 reject their survival. All are consistent with the stated dispositions. **PR-6 passes; no census gap or procedural refusal applies.**

### F-037 — fixed in the operative text

| Surface / attempted counterexample | Current rule and result |
|---|---|
| Inherited root `PATH` | `plan:235-267` defines the Root tool path and production launch form. Both Unix launchers, the setup header and the README run lines must use absolute `/usr/bin/sudo /bin/bash -p`; `plan:1031-1035`, `:1131-1133`, `:1183-1185`; `task:57-58` assign those edits. A caller-owned `sudo` or `bash` cannot be chosen by these launch forms. |
| Before the first root measurement/action | Load guard → `main` → `clean_start` → clean `/bin/bash -p` re-exec → Load guard → `main` → checked marker/environment → fixed path/cache/aliases → `check_root_tools` → original root/account/drive checks → WP-U5 steps. The only external command preceding the Root tool check is absolute `/usr/bin/env`, which starts absolute `/bin/bash`; `plan:238-260`, `:397-404`, `:702-711`, `:1031-1078`. No Mode reader, `uname`, `id`, `stat`, download or write precedes that boundary. |
| Stale command lookup, aliases and functions | Fresh shell plus explicit `hash -r` and `unalias -a`; `-p` forbids environment-imported functions. The tool check uses `command -v` and accepts only the exact system-folder/name form, rejecting a file-defined tool function, alias, builtin or other location before any write, with the name/lookup and stop 6; `plan:243-260`, `:1046-1074`, `:1306-1315`. |
| Startup files and forged marker | The initial production Bash already has `-p`, protecting the interval before any script statement. The clean start drops the caller's environment, including `HOME`, `BASH_ENV` and `ENV`; it requires privileged mode and the exported-name allow-list on a marked run. `SHELLOPTS`, `BASHOPTS`, `CDPATH` and `GLOBIGNORE` cannot supply startup behavior under `-p`; `plan:240-250`. A marker is not authorization to bypass those checks. |
| All root tools, including optional packages | `root_tools` must name **each** external root command, with the floor at `plan:254-256`, not merely the PowerShell tools. Every present tool must resolve within the protected system folders; a missing optional/platform/package tool is allowed to remain absent, never to fall back to an account folder. WP-U5 step 3 repeats the check after installation (`plan:258`, `:710-711`). An unsafe resolution fails before the initial writes; this is not a claim that the package-install recheck undoes earlier installation. |
| Account discovery / installed archive | Existing `pwsh` discovery and execution stay inside `sudo -u "$user" -i`; root executes only the newly downloaded/hash-checked binary under the protected version tree, after the parent and regular-file checks; `plan:978-1025`. Fixing root lookup does not move account discovery to root. |
| Package-manager folders | The Parent walk still refuses an account-owned install/bin parent and changes no existing folder's owner or mode. Homebrew's account-owned bin directory remains a named stop with the documented account-install remedy; `plan:1000-1006`, `:1178-1182`, `:1311-1314`, A-19. |
| Reachable negative oracle | AC-32 (`plan:1112`) runs the setup **as a file**, through its `main`, with hostile `PATH` programs and exported `id`/`stat`/`tar` functions. It asserts zero fake markers, protected `stat`/`tar`/`install` lookups, and the real nonroot refusal. Additional cases cover initial `-p` plus `BASH_ENV`, forged markers with/without `-p`, a file-defined `stat` and missing guards. Launcher/header static assertions and the complete root-tool floor are required. `task:57` row 8b owns these tests and runs the AC-32 Red check and targeted suite; row 9 owns the README assertion. A helper-only or test-only resolver cannot satisfy this contract. |

The source-based attempted refutation now fails: unlike round 9, the trusted lookup is produced by the setup entrypoint itself, before its first external measurement or action, rather than only inside the later installed helper. Both measurement (`stat`) and action (`tar` / `install`) surfaces are named, observed and adversarially tested. The [Bash reference manual, privileged mode](https://tiswww.case.edu/php/chet/bash/bashref.html#The-Set-Builtin) confirms the startup/function behavior; the [upstream sudoers manual, `secure_path`](https://raw.githubusercontent.com/sudo-project/sudo/main/docs/sudoers.man.in) confirms why the absolute initial launch and fixed path matter. The GNU-hosted manual fetch timed out; the same primary manual was read at the maintainer-hosted address and cross-checked with installed Bash builtin help and scratch behavior.

**The round-9 qualification is removed: no account-controlled executable can run as root during setup through the specified production entrypoints.** This is the plan contract under its accepted trusted-drive and protected-system boundary, not a claim of implemented/live proof. The prose warning about manually typing bare `sudo bash` (`plan:166-167`, `:265-267`) correctly describes an unsafe alternative before the prescribed entrypoint; the shipped launchers and documented run lines must use the absolute form. The already accepted ability to alter drive-carried code and D-1's configured-repository package residual are not reopened.

### F-038 / F-039 — fixed without losing meaning

- **F-038:** `plan:959-960` alone supplies `RELEASE_PAGE_LIMIT = 10`. Step 1's refusal, Probe-3 (`:1086`), Link Boundary row (`:1101`), AC-32 (`:1112`), Spec/Files rows (`:1122`, `:1130`), stop 13 (`:1326-1328`) and `task:57` reference that limit. AC-32 reads the constant rather than embedding a second cap. Full-list-before-selection, next-link host refusal, cap exhaustion and zero writes on refusal retain their meaning; no release-selection rule changed.
- **F-039:** the PowerShell Boundary row (`plan:1105`) refers to the Parent walk (`:228-231`) and its named failure, while retaining physical-path equality and the separate regular-root-file check via steps 4, 7 and 8 (`:1000-1025`). No owner, write-bit, sticky-directory or leaf/symlink protection was dropped.

The root folder list has one governing definition at `plan:235`; the exact sudoers serialization at `:270` explicitly binds its value to that definition at `:271`. This is not an independently selectable policy. The new sketch is explicitly subordinate to the definition (`:1035`). No materially different competing rule or new single-statement defect was found.

### Regression and whole-plan coverage

| Scope | Current verification |
|---|---|
| Review extension and human decisions | `plan:90-95`, `:124-126`; `task:36` record round 10 and the exact quote "fix and add round 10". D-1, D-2 and D-3 Decision Log records at `plan:1422-1441`, `:1622-1631` are byte-identical to the round-9 input: 1,956, 1,277 and 1,496 characters. All stay ruled A; no choice was re-decided. |
| F-027 | Existing `pwsh` lookup/run remains account-side (`plan:981-994`), with AC-32's account-identity negative and `task:57`. Root utility selection is now fixed separately above. |
| F-028 | Parent walk, physical equality, deepest-existing ancestor, protected download/stage, regular non-symlink root-owned binary, rechecks before execution/link and no package-folder takeover remain intact (`plan:228-234`, `:1000-1026`, `:1105`, `:1112`). |
| F-029 | Absolute fallback remains installation evidence only; later Unix member provisioning owns the process-environment lookup (`plan:1088-1094`, `:1214-1218`, `:1282-1283`, `:1347`; `task:62-63`). Actual `fleet.py:1641-1643`, `:1788-1789` still use the member process's own lookup. |
| F-030 | Full pagination, winner on page 2, foreign-host refusal, exhaustion at the named cap and no-write failure remain specified (`plan:956-972`, `:1101`, `:1112`, `:1326-1328`; `task:57`). |
| F-031 | Both tar specifications still use `tar --no-same-owner -xzf "$archive" -C "$stage"` (`plan:1015`, A-19 at `:1637`); the correction did not change argv. |
| F-032 | Probe-3 still follows pure-helper creation and passing AC-32, before drive/member writes; mode-specific imports remain deferred (`plan:1082-1086`, `:1210-1214`; `task:44`, `:57`). |
| F-033 | A-21 (`plan:1652-1661`) remains the canonical release-selection predicate; the numeric pagination cap is a distinct definition. |
| F-034 / F-035 | Used-drive explanation still includes `pwsh-pin.txt` (`plan:1165-1171`; `task:58`). WP-U6p and row 8b still use `compact_continue` with matching expanded reread/output lists (`plan:74`; `task:57`). |
| Definitions, ACs, stops and cross-references | All 26 definitions, 32 distinct ACs and 25 Decision Log entries (A-1–A-22, D-1–D-3) resolve. Of 34 AC rows, only AC-26, AC-32 and AC-21 changed; the other 31 are byte-identical to the round-9 input. Only stops 6 and 13 changed, adding the root-entry checks and named-cap reference without removing prior refusals. `AC_COUNT` remains 32. |
| Dependencies / every task row | All 11 WP and 44 task nodes resolve and are acyclic. WP-U6p follows WP-U6 and precedes WP-U7; row 8b follows 8a and precedes 9. All 44 statuses remain unchecked. Required roles, deliverables, validations and statuses pass task lint; every inline Python validation parses. |
| Artifact existence before command semantics | Every referenced executable/test/template/schema is present or explicitly scheduled. Row 1 creates the three plan-local checkers; rows 2–4 create the planned tests/helper; H1/H2 create the named closeout artifacts. The absent MEU registry is an explicit no-op assertion. No unscheduled missing validator was found. The distinct tracked-file inventory is 23, matching `task:14`. |
| AC-1–AC-13, AC-26, AC-28 | Retired-name removal and update order, load guards, Bash/PowerShell compatibility, privacy, characterization, Git-bash locator, helper verb/argument/path/environment controls, admin outcomes and Windows active-store firewall/report behavior keep their callers and negative cases. |
| AC-14–AC-21, AC-27, AC-31 | Console checks, subnet/listener/firewalld sequencing and reports, key-auth prerequisite, password-off rollback, record retirement/name-clash handling, hub password probe, image/CLI verification, drive trust and fingerprint/pin refusal keep their meaning. |
| AC-22–AC-25, AC-29–AC-30, AC-32 | Baseline comparison, AC coverage, live installation evidence, privacy scope, state identity and the expanded root-entry boundary remain assigned to concrete task rows, producers and failing cases. None is claimed executed as future implementation. |
| Scope and security canon | No GitHub credential is placed on a member: releases metadata is fetched anonymously on the hub and member archive downloads require no sign-in (`plan:956-972`, `:1007-1013`). No new port is introduced by the correction. The prior explicit SSH-kit port-22 exception (`plan:1144-1145`) is distinct from the bootstrap prohibition on a fleet member listener. No secret/sign-in/key file was read or written or copied into review evidence; the no-secret stop remains `plan:1317`. |
| Usability / complexity | Absolute launch forms remove reliance on account PATH without adding a new human design gate. Homebrew, older/broken existing PowerShell, unsupported platform/dependency and release-selection stops retain concrete messages/remedies. No additional complexity concern with a demonstrated delivery failure remains. |

### Executed evidence and limits

Working receipts/scripts are under `review evidence in C:/Temp/zorivest/usb-kit-plan/review-r10/`. Both full diffs were generated independently: **19 plan hunks and 3 task hunks**. Reproduced current hashes are **plan `c55bcae167acc971fb9c64e8ee0d25ccdec7630f85b15b616f35f5d4d350b0cc` (1,809 lines)** and **task `0561afd386a33281fcc37d11a0ab04a66a82f5439b25e3c37fd1ff5c8ace11d3` (110 lines)**. The round-9 before-copy hashes match its recorded input hashes. All ten protected plan/task/kit hashes remain unchanged.

```json
{
  "schema_version": "evidence.v1",
  "check_id": "r10-census-and-contract",
  "command": "rtk proxy python -X utf8 -B C:/Temp/zorivest/usb-kit-plan/review-r10/audit.py",
  "cwd": ".",
  "scope": "Independent raw census reconstruction, disposition identity/classification, diffs, decisions, counts, references, dependency graphs and inline Python parse",
  "phase": "static",
  "exit_code": 0,
  "result": "pass",
  "tested_state": "plan c55bcae167acc971fb9c64e8ee0d25ccdec7630f85b15b616f35f5d4d350b0cc; task 0561afd386a33281fcc37d11a0ab04a66a82f5439b25e3c37fd1ff5c8ace11d3",
  "output": "68 terms; 204 searches; 447 hits/map rows; 114 zero rows; 337 updated; 110 confirmed-consistent; D-1/D-2/D-3 unchanged; 32 AC IDs; 26 definitions; 13 stops; 11 WP and 44 task nodes acyclic; ERRORS []"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "r10-task-lint",
  "command": "rtk proxy python -X utf8 -B core/tools/lint_task_contract.py --task docs/execution/plans/2026-11-07-usb-kit-hardening/task.md",
  "cwd": ".",
  "scope": "Current task contract",
  "phase": "static",
  "exit_code": 0,
  "result": "pass",
  "tested_state": "task 0561afd386a33281fcc37d11a0ab04a66a82f5439b25e3c37fd1ff5c8ace11d3",
  "output": "OK: 44 rows; 42 fully checked; dependencies resolve and are acyclic; 2 view_file exemptions H1-5 and H2-1"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "r10-inert-clean-start-probe",
  "command": "rtk proxy python -X utf8 -B C:/Temp/zorivest/usb-kit-plan/review-r10/clean_start_probe.py",
  "cwd": ".",
  "scope": "Only the literal clean_start/check_root_tools sketch plus inert scratch main; no setup, launcher, sudo or elevation",
  "phase": "targeted",
  "exit_code": 0,
  "result": "pass",
  "tested_state": "Current plan sketch; installed Git bash; scratch fake executables/functions/startup file, alias and hash entry",
  "output": "Hostile PATH/functions and privileged BASH_ENV cases: exit 0, no fake marker, id/stat/tar/install resolve under /usr/bin. Forged markers with/without -p: exit 17, clean-start failure, no marker. File-defined stat function: exit 17, stat lookup named, no marker. Alias and stale hash cases: exit 0, no marker. bash -n exit 0. Installed Bash builtin help captured. No root execution was performed."
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "r10-existing-security-static-tests",
  "command": "rtk proxy python -X utf8 -B -m pytest scripts/tests/test_fleet_bootstrap.py scripts/tests/test_fleet_agent.py -q -p no:cacheprovider --basetemp=C:/Temp/zorivest/usb-kit-plan/review-r10/pytest-temp -k \"(test_ac19_the and not effort) or test_ac32_forbidden\"",
  "cwd": ".",
  "scope": "Existing bootstrap contract/deletion guards and unchanged forbidden-command set",
  "phase": "targeted",
  "exit_code": 0,
  "result": "pass",
  "tested_state": "Unchanged existing fleet/bootstrap source and tests",
  "output": "7 passed, 316 deselected in 0.14s"
}
```

Also ran the read-only `contracts.py` audit (exit 0): referenced artifacts present/scheduled, 23 distinct planned tracked paths, 31 unchanged AC rows, only stops 6/13 changed, the single page-limit definition, exact before hashes and ten protected input hashes unchanged. Read-only Git/status/diff and file inspections support the state above. Public primary documentation was read over HTTPS without credentials. No hub/member/SSH connection, setup/launcher, prepare/import, installer, sudo/visudo, credential read, Git write or PowerShell installation occurred.

These are plan-review/static and inert-probe results. Future AC-32 tests, live macOS Bash 3.2 behavior, package installs and the full execution gate remain execution work. Existing accepted residuals remain explicit: writable-drive code trust, first-import fingerprint comparison, configured-package root access under D-1, full Windows administrator, D-2 installer-before-verification, supported-platform/dependency stops, existing-version retention and the later Unix member PATH prerequisite.

### Checklist results

| Check | Result | Evidence |
|---|---|---|
| PR-1 | pass | Full plan/task read and both diffs; matching work, scope and task order. |
| PR-2 | pass | 44 unchecked task rows; no project implementation handoff; unrelated dirty work preserved. |
| PR-3 | pass | Task lint: 44 rows, 42 checked command rows and 2 source-read exemptions. |
| PR-4 | pass | All validation artifacts present or scheduled; changed commands read; entrypoint negatives bound to row 8b. |
| PR-5 | pass | D-1/D-2/D-3 unchanged A rulings; A-22 and changed ACs cite canon/primary sources. |
| PR-6 | pass | 204 raw searches independently reproduced; 447 matching dispositions and 114 zero records; cited reasons checked. |
| PR-7 | pass | Exclusions retain their evidence and approved scope; no disguised new deferral. |
| PR-8 | pass | Root-entry control has a producer/call chain, lookup/marker observables and hostile negatives; prior controls preserved. |
| PR-9 | pass | F-038/F-039 centralized; governing definitions referenced; no competing behavior. |
| DR-1 | pass | Correction claims match operative plan/task changes; no implementation-complete claim. |
| DR-2 | pass | Old/new/variant terms and complete diffs checked; remaining old hit is consistent. |
| DR-3 | pass | Launchers, README, task outputs and reread references updated in the plan; future artifacts explicitly scheduled. |
| DR-4 | pass | AC-32 tests the production file entrypoint, startup/functions, measurement/action lookups and omitted guards. |
| DR-5 | pass | Reproducible commands, preserved raw census/diffs and decisive evidence recorded above. |
| DR-6 | pass | Root/account identity, folder boundaries, AC/task ownership and bootstrap security rules agree. |
| DR-7 | pass | Hashes, counts, decision identity and census totals independently reproduced. |
| DR-8 | pass | Plan approval distinguished from implementation/live verification; accepted residuals remain explicit. |
| Review scope preservation | pass | Only rolling review changed in repository; all earlier text retained except required frontmatter fields; ten inputs unchanged. |

### Verdict and next gate

**`approved` — round 10 of 10.** F-037's delivery-level defect is fixed; F-038/F-039 are also fixed; no newly introduced or remaining supported defect requires correction. The human now has the final review record. Execution requires the existing human proceed gate and row 0; this review starts no correction loop, setup, execution or commit.

### Structured verdict — Round 10


```json
{
  "schema_version": "review-verdict.v1",
  "date": "2026-11-14",
  "review_mode": "plan",
  "target_plan": "docs/execution/plans/2026-11-07-usb-kit-hardening",
  "agent": "Codex",
  "requested_verbosity": "detailed",
  "verdict": "approved",
  "summary": "Round 10 of 10 approved. F-037, F-038 and F-039 fixed; F-027 through F-035 remain fixed and F-036 remains closed. No new findings. PR-6: 204 searches, 447 hits/dispositions and 114 zero-hit records independently verified. Task lint, seven existing static tests and inert clean-start probes pass. Plan approval only; execution remains subject to the human proceed gate and row 0. Review: .agent/context/handoffs/2026-11-07-usb-kit-hardening-plan-critical-review.md",
  "findings": [],
  "checklist_results": [
    {
      "check": "PR-1",
      "result": "pass",
      "evidence": "Full plan/task read and both diffs; matching work, scope and task order."
    },
    {
      "check": "PR-2",
      "result": "pass",
      "evidence": "44 unchecked task rows; no project implementation handoff; unrelated dirty work preserved."
    },
    {
      "check": "PR-3",
      "result": "pass",
      "evidence": "Task lint: 44 rows, 42 checked command rows and 2 source-read exemptions."
    },
    {
      "check": "PR-4",
      "result": "pass",
      "evidence": "All validation artifacts present or scheduled; changed commands read; entrypoint negatives bound to row 8b."
    },
    {
      "check": "PR-5",
      "result": "pass",
      "evidence": "D-1/D-2/D-3 unchanged A rulings; A-22 and changed ACs cite canon/primary sources."
    },
    {
      "check": "PR-6",
      "result": "pass",
      "evidence": "204 raw searches independently reproduced; 447 matching dispositions and 114 zero records; cited reasons checked."
    },
    {
      "check": "PR-7",
      "result": "pass",
      "evidence": "Exclusions retain their evidence and approved scope; no disguised new deferral."
    },
    {
      "check": "PR-8",
      "result": "pass",
      "evidence": "Root-entry control has a producer/call chain, lookup/marker observables and hostile negatives; prior controls preserved."
    },
    {
      "check": "PR-9",
      "result": "pass",
      "evidence": "F-038/F-039 centralized; governing definitions referenced; no competing behavior."
    },
    {
      "check": "DR-1",
      "result": "pass",
      "evidence": "Correction claims match operative plan/task changes; no implementation-complete claim."
    },
    {
      "check": "DR-2",
      "result": "pass",
      "evidence": "Old/new/variant terms and complete diffs checked; remaining old hit is consistent."
    },
    {
      "check": "DR-3",
      "result": "pass",
      "evidence": "Launchers, README, task outputs and reread references updated in the plan; future artifacts explicitly scheduled."
    },
    {
      "check": "DR-4",
      "result": "pass",
      "evidence": "AC-32 tests the production file entrypoint, startup/functions, measurement/action lookups and omitted guards."
    },
    {
      "check": "DR-5",
      "result": "pass",
      "evidence": "Reproducible commands, preserved raw census/diffs and decisive evidence recorded above."
    },
    {
      "check": "DR-6",
      "result": "pass",
      "evidence": "Root/account identity, folder boundaries, AC/task ownership and bootstrap security rules agree."
    },
    {
      "check": "DR-7",
      "result": "pass",
      "evidence": "Hashes, counts, decision identity and census totals independently reproduced."
    },
    {
      "check": "DR-8",
      "result": "pass",
      "evidence": "Plan approval distinguished from implementation/live verification; accepted residuals remain explicit."
    },
    {
      "check": "Review scope preservation",
      "result": "pass",
      "evidence": "Only rolling review changed in repository; all earlier text retained except required frontmatter fields; ten inputs unchanged."
    }
  ]
}
```

🕐 Completed: 2026-11-14 22:01 (EST)
