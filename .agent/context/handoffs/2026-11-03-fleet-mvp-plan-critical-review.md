---
date: "2026-11-03"
review_mode: "plan"
target_plan: "docs/execution/plans/2026-11-03-fleet-mvp/implementation-plan.md"
verdict: "approved"
findings_count: 0
template_version: "2.2"
requested_verbosity: "standard"
agent: "gpt-6.1-sol"
loop_id: "plan-2026-11-03-fleet-mvp"
round: 2
---

# Critical Review: 2026-11-03-fleet-mvp

> **Review Mode**: `plan`
> **Verdict**: `changes_required`

## Intent Anchor

"Build the MVP of a stdlib-only hub on <hub host> and a pull-only member so that a <hub host> session can run a project's checks on its uncommitted tree on <member host> and get back the exit code, log and tree id, with authority enforced by the hub."

**Intent achieved: partial.** The proposed transport and work packages fit that goal, but the allowed `run` path bypasses the asserted operation restrictions, two safety oracles can pass despite their protected property failing, and the live sequence omits project-tool provisioning.

## Scope

**Targets:** `docs/execution/plans/2026-11-03-fleet-mvp/implementation-plan.md` and `task.md`.
**Review type:** unstarted execution plan; PR-1 through PR-9 and applicable DR checks.

Read the accepted outline, binding fleet handoff, all four `docs/research/fleet/` files, the named av-kit instructions and command reference, local firewall instructions, create-plan workflow, plan/task/review templates, and the precedent task. Older proposals are reference material, not additional scope. D-1/D-2/D-3 are accepted; this review does not reopen the transport decision or require P4–P7 implementation.

All 15 numbered implementation rows (0–14) are unchecked. The fleet source, tests, templates, plan-local checkers and implementation handoffs are absent and scheduled outputs; their absence is expected. The task linter passes. The live registry's `independent_reviewer.bindings.codex-cli.slug` is `gpt-6.1-sol` (`P:/.agent/model-registry.yaml:660–677`); the plan author is Claude.

Reviewed input SHA-256:

| File | SHA-256 |
|---|---|
| implementation-plan.md | `4585443eaf438b298febf3d019fe1b53271416cf63c1c4ce02ec09caa0335962` |
| task.md | `593ee26fbc2939f7ad5bc70a2b8c8c3e311411f4fae333292d77c4a8267c3204` |

## Findings

All findings concern the **deliverable** and have **High confidence**. Short file references below resolve inside the target plan folder. The first four findings block; the two clerical notes do not.

| # | Severity | Blocking | Kind | Finding | File:Line | Recommendation | Status |
|---|----------|----------|------|---------|-----------|----------------|--------|
| F-001 | High | yes | control-defeat | **An allowed `run` task can perform the operations the protocol says it forbids.** `mechanism: unchecked-manifest-execution`. The complete chain is orchestrator `run` → accepted `run` envelope → bundle manifest → arbitrary argv → `execute_run`. AC-22 validates shape, not operation authority. A command can be `git -c user.name=fleet -c user.email=fleet@example.invalid -c commit.gpgsign=false commit --allow-empty -m x`, or `git push <explicit-repository> HEAD:refs/heads/main`. Neither needs an `origin`; an explicit local repository needs no GitHub credentials. A command can also invoke the installed agent CLI while the `agent` kind is disabled. The plan explicitly tolerates slot commits at line 360. Thus AC-8's kind rejection and AC-28's failure of `push origin` can both pass while a task causes a forbidden operation. **Violates AC-8**, its D-2/outline §2.6 source, and the binding handoff §3 authority rule. | `implementation-plan.md:233`, `:328`, `:350`, `:359`, `:368`, `:383` | Resolve the `run` trust/authority boundary before coding. Establish command authority independently of a mutable task snapshot and exercise prohibited operations through the accepted `run` route, including scripts and explicit push destinations. Do not claim that no remote enforces a push prohibition. If the intended guarantee is narrower, obtain a human ruling rather than silently weakening the binding rule. | open |
| F-002 | High | yes | control-defeat | **Zero completed HTTP requests does not prove zero key bytes sent before pin validation.** `mechanism: request-count-secret-oracle`. AC-5 observes only exit/code and request count. A client can write the request line and an Authorization header, stall before the final header terminator, then refuse the pin. A server that times out parsing headers records no handled request although it received the key. A local decoded-HTTP probe demonstrated `complete_http_requests: 0` and `key_received: true`. The specified wrong-pin assertions can therefore pass with their protected secret already disclosed. **Violates AC-5** and D-1's pre-key pin boundary. | `implementation-plan.md:174`, `:230` | Capture all application bytes received after the TLS handshake on the mismatched-pin connection and require zero, including partial/invalid requests. Prove this oracle rejects a client mutation that writes a fake-key header before checking the pin. Exercise both authenticated requests and the pairing path with the shared transport. | open |
| F-003 | High | yes | behavior | **The live av-kit run is sequenced before its missing toolchain is provisioned.** WP-2 installs Python/git and runs generic `check`; its project-specific installation is conditional on a published project. The av-kit manifest is first published in task row 12, after <member host>'s bootstrap and update gates, and that row immediately runs `setup` and the checks. Nothing reruns `check --project av-kit` or installs the required project executables on <member host>. The binding handoff's inventory records uv and Node absent, and the registered checks require uv/npm. `setup` cannot run `uv sync` or `npm ci` when those executables are absent: `execute_run` rejects with `tool_missing` before the checks execute. Allowing av-kit test failures does not make a pre-execution tool rejection satisfy the MVP. **Violates AC-31** and outline P3's done condition. | `implementation-plan.md:273`, `:279`, `:351`, `:386`; `task.md:48`, `:51`, `:52`; binding handoff `:127–128` | Add the existing project-check/install step after publishing the manifest and before the first run, at <member host>'s console through its setup agent. Extend an existing human gate if convenient. Record the required tool versions and require the check to pass before submitting `setup`; no new service or installer framework is needed. | open |
| F-004 | High | yes | control-defeat | **AC-23 does not observe working-tree content preservation.** `mechanism: porcelain-content-oracle`. The bundle tree proves what was captured; index bytes, HEAD, refs and porcelain do not prove what remains in the source tree. A defective `make_snapshot` can build the correct bundle and then overwrite an already-untracked or already-dirty file. Its porcelain entry stays identical, and every other listed before/after observable can remain equal. A disposable fixture demonstrated `?? untracked.txt` before and after a content replacement. The planned test can approve a snapshotter that clobbers another active session's files. **Violates AC-23** and the stated unchanged-working-tree contract. | `implementation-plan.md:87`, `:341`, `:378` | Record and compare source fixture path/content identities independently of the bundle and porcelain, including ignored files that must remain untouched. Include a mutation that corrupts a source file after the bundle is produced; require failure. Keep the existing real-index, HEAD and ref checks. | open |
| F-005 | Low | no | clerical | **The stop wording includes the snapshot's own plumbing commit.** Stop condition 6 says to stop if anything needs a commit, while snapshot step 3 necessarily uses `git commit-tree`. The intended exception is inferable from the approved bundle/snapshot design. | `implementation-plan.md:337`, `:420` | Distinguish the specified temporary snapshot commit object from a commit that lands work or changes a branch; preserve the latter's human gate. | open |
| F-006 | Low | no | clerical | **The firewall checklist omits fields and service checks needed by its cited practice.** `Get-NetFirewallRule` alone does not include the associated remote-address/port filters; the row also omits the local instruction to confirm Plex and `FPS-SMB-In-TCP` after a Windows rule change. The intended local observer is evident, so this is a checklist correction, not a demonstrated false pass of the unwritten checker. The rule name/port/LAN scope are also restated in both the AC and task. | `implementation-plan.md:305`; `task.md:47`; `the local network notes (lines 145-149)` | Capture the associated address and port filters, profile state, and required Plex/SMB checks in the human records. Make AC-20 the canonical firewall policy and keep the executable checklist consistent with it. | open |

## Checklist Results

### Plan Review

The results below assess the plan and its proposed tests; none reports a fleet implementation test pass.

| Check | Result | Observed evidence |
|---|---|---|
| PR-1 Plan/task alignment | partial | WP-1–WP-3, 32 ACs and task dependencies align overall. F-003 identifies the missing live prerequisite. |
| PR-2 Not-started confirmation | pass | 15/15 implementation rows unchecked; new fleet source, tests and implementation handoffs absent. |
| PR-3 Task contract completeness | pass | Linter: 37 rows, 10 columns, 35 fully checked, two source-read exemptions; dependencies resolve and are acyclic. |
| PR-4 Validation realism | fail | F-002 and F-004 demonstrate material false passes. Invoked existing tools are present; absent checkers/tests are expressly scheduled to be written. |
| PR-5 Source-backed planning | partial | AC source labels and decision log exist. F-001 conflicts with the binding authority claim. Older proposals are correctly treated as reference. |
| PR-6 Handoff/corrections readiness | pass | One project handoff and both rolling reviews are explicit. Round-2 correction census is not applicable. |
| PR-7 Scope discipline | pass | P4–P7, internet exposure, extra transports and result landing are excluded on accepted scope. Existing package failures are baseline comparisons, not missing MVP work. |
| PR-8 Reachability, totality and atomicity | fail | HTTP/CLI/member/local chains are named. `BEGIN IMMEDIATE` explicitly covers submit/claim/status/pair/approve/revoke/publish; blob replacement is named. No missing atomicity mechanism was found. Authority and pin oracles still have F-001/F-002. |
| PR-9 Single-statement discipline | partial | Named protocol/state/limit definitions are a useful canonical source. Firewall literals recur across AC-20 and task row 7 (F-006); no conflicting second live policy was found. |
| DR-1/DR-5/DR-7/DR-8 | pass | Draft state is distinguished from future work; evidence below preserves observed exits and decisive results. No implementation-complete or fresh-full-suite claim is made. |
| DR-2/DR-3/DR-6 | pass within plan scope | No rename migration is proposed. Plan/task/source cross-references were checked; known red reference/sanitize baselines were read rather than charged to the fleet. |

### Acceptance-criterion falsification audit

| ACs | Assessment |
|---|---|
| AC-1–4 | Shape/type, exhaustive state-pair, append-only SQL and mutated-source negatives can falsify the specified properties. Source mutations are test copies. |
| AC-5 | Insufficient secret-egress observable: F-002. |
| AC-6–8 | HTTP authentication, human code/TTY, sender identity and role negatives are concrete. Pair/name decisions are transaction-bound. Closed task kinds do not constrain the allowed executor's effects: F-001. |
| AC-9–15 | Real subprocess skeleton, concurrent/repeated claim, terminal/idempotent status, offline/restart and handshake-stall tests are meaningful. AC-9's stopped-member fixture must age past `OFFLINE_AFTER_S` before expecting offline rather than timeout. |
| AC-16–19 | The route walk, fixed bootstrap mapping, served-byte hashes, missing-tool result and mutated template provide real negative cases. No implementation claim is inferred from these planned tests. |
| AC-20–21 | Human-gated observations and <member host> preservation report are executable in principle. Complete the local firewall checklist as F-006. Row 9 checks row 8's report contents, so row 8's file-existence check is not treated as the final live proof. |
| AC-22 | Manifest-shape negatives are meaningful but do not establish operation authority (F-001). |
| AC-23 | Captured tree, real index, HEAD and refs are observed; surviving source contents are not: F-004. The temp-ref cleanup failure path is explicitly tested. |
| AC-24 | Filename-pattern refusals and zero upload/message counts can fail. This is a likely-secret-filename filter, not a general secret/content/history scanner. |
| AC-25–27 | Real marker/log/result round-trip, first-failure sentinel, rejected-task sentinel, hash/size and member blob-access negatives are concrete. |
| AC-28 | Detached/no-remote/no-branch properties are measurable; the asserted inability to push does not follow: F-001. |
| AC-29–30 | Child timeout sentinel and live heartbeat observations can fail. Environment canary checks billing variables reach children unchanged; it does not itself govern what arbitrary manifest programs do. |
| AC-31 | Result/schema/tree checks are useful, but the task sequence cannot guarantee the tools needed to execute the checks: F-003. |
| AC-32 | New-failure baseline mutation and full pytest are appropriate. Test-name coverage is an inventory check, not a substitute for the separately required passing targeted tests. |

### Reproducible observations

```json
{"schema_version":"evidence.v1","check_id":"r1-task-contract","command":"rtk proxy python -B core/tools/lint_task_contract.py --task docs/execution/plans/2026-11-03-fleet-mvp/task.md *> C:/Temp/agentic-framework/receipts/fleet-review-r1-task-lint.txt; $rc=$LASTEXITCODE; rtk read C:/Temp/agentic-framework/receipts/fleet-review-r1-task-lint.txt; exit $rc","cwd":"P:/agentic-framework","phase":"static","scope":"Task syntax, rows, receipt/exit contract and dependency graph","tested_state":"task SHA-256 593ee26fbc2939f7ad5bc70a2b8c8c3e311411f4fae333292d77c4a8267c3204","exit_code":0,"result":"pass","output":"OK: 37 row(s); 10-column table (with builder_model); 35 row(s) fully checked: backticked, exit-code re-raised, receipt under RECEIPTS_DIR; dependencies resolve and are acyclic; 2 row(s) exempt (view_file): H1-5, H2-1"}
```

```json
{"schema_version":"evidence.v1","check_id":"r1-inventory","command":null,"procedure":"Enumerated numbered implementation rows in task.md and tested existence of scheduled fleet source, harness, three test files, bootstrap/manifest templates, two plan-local checkers, the project handoff and rolling implementation review; cross-checked absent files against Files Modified and task rows. Checked existing refcheck, sanitize, lint, closeout, evidence, ledger and issue-triage tools and handoff/reflection resources.","observer":"gpt-6.1-sol","exit_code":null,"phase":"manual","scope":"PR-2 and referenced-artifact existence","result":"pass","output":"15 implementation rows, all unchecked. New fleet artifacts and implementation handoffs absent, all scheduled. Existing validation tools and resources present. Canonical plan-review file did not exist before this review."}
```

```json
{"schema_version":"evidence.v1","check_id":"r1-pin-oracle","command":null,"procedure":"Executed a disposable inline Python probe using HTTPServer/BaseHTTPRequestHandler on 127.0.0.1. Wrapped rfile.readline to capture received bytes and counted do_GET calls. Sent a GET line and Authorization header containing FAKE-REVIEW-CANARY, omitted the blank header terminator, and allowed the handler's 0.1-second read timeout before closing. Compared received bytes with completed-handler count. This tests the decoded HTTP observation, not a fleet TLS implementation.","observer":"gpt-6.1-sol","exit_code":null,"phase":"manual","scope":"AC-5 request-count inference","result":"fail","output":"Probe process exit 0: complete_http_requests=0; key_received=true. Therefore the proposed request-count oracle can miss key-bearing partial traffic. An earlier EOF-only variant exited 1 because BaseHTTPRequestHandler accepted EOF as header completion; that rejected variant is not the counterexample."}
```

```json
{"schema_version":"evidence.v1","check_id":"r1-source-content-oracle","command":null,"procedure":"Created a disposable git-init fixture under the receipts root without making a commit. Wrote untracked.txt as original, ran git status --porcelain, replaced its content with clobbered, and repeated status. Compared the statuses and read the changed file. No av-kit repository operation was performed.","observer":"gpt-6.1-sol","exit_code":null,"phase":"manual","scope":"AC-23 working-tree preservation inference","result":"fail","output":"Probe process exit 0: before='?? untracked.txt\\n'; after='?? untracked.txt\\n'; porcelain_equal=true; file_content_changed=true. A post-bundle clobber can leave all specified repository observables equal."}
```

```json
{"schema_version":"evidence.v1","check_id":"r1-git-explicit-destination","command":"rtk proxy git push -h *> C:/Temp/agentic-framework/receipts/fleet-review-r1-git-push-help.txt; $rc=$LASTEXITCODE; rtk read C:/Temp/agentic-framework/receipts/fleet-review-r1-git-push-help.txt; exit $rc","cwd":"P:/agentic-framework","phase":"static","scope":"AC-28 no-origin inference; help only, no push","exit_code":0,"result":"pass","output":"usage: git push [<options>] [<repository> [<refspec>...]]; --[no-]repo <repository>. Git accepts an explicit destination; origin is not a required argument or precondition."}
```

```json
{"schema_version":"evidence.v1","check_id":"r1-source-and-live-sequence","command":null,"procedure":"Traced C-HTTP/C-CLI/C-MEMBER/C-LOCAL, every AC negative, task rows 5 through 12, the bootstrap/project-check steps and the manifest argv validator. Compared these with outline P1–P3 and D-1/D-2/D-3, binding handoff section 3 and inventory, av-kit line 102 and registered checks, local change discipline, and the package baseline files.","observer":"gpt-6.1-sol","exit_code":null,"phase":"manual","scope":"PR-1/4/5/7/8/9 and all 32 ACs","result":"fail","output":"Found F-001 through F-004. Claim/status/pair transactions are explicitly BEGIN IMMEDIATE; new code/test/checker paths are planned deliverables. Saved baselines already show 18 unresolved references and 3 unclassified tools; sanitize also records the pre-existing raw-slug, registry-lookup and prose-model failures. These baseline failures are not new fleet findings."}
```

```json
{"schema_version":"evidence.v1","check_id":"r1-review-parse","command":"rtk proxy python -B core/tools/validate_closeout_artifacts.py --review .agent/context/handoffs/2026-11-03-fleet-mvp-plan-critical-review.md --review-state-only --expected-review-mode plan --expected-target-plan docs/execution/plans/2026-11-03-fleet-mvp/implementation-plan.md --max-review-rounds 3 --output C:/Temp/agentic-framework/receipts/fleet-review-r1-parsed-state.json *> C:/Temp/agentic-framework/receipts/fleet-review-r1-parse.txt; $rc=$LASTEXITCODE; rtk read C:/Temp/agentic-framework/receipts/fleet-review-r1-parse.txt; exit $rc","cwd":"P:/agentic-framework","phase":"static","scope":"Canonical review mode, target, round, verdict and blocking findings","exit_code":0,"result":"pass","output":"OK: review_mode=plan; round 1 of 3; verdict=changes_required; open findings=4. This parser result is artifact validation, not ledger approval."}
```

```json
{"schema_version":"evidence.v1","check_id":"r1-write-scope","command":null,"procedure":"Recomputed SHA-256 for both target plan files after writing the review and compared with the pre-review hashes. Ran rtk proxy git --no-optional-locks diff --exit-code with a raw receipt and preserved exit. Compared the untracked file inventory with the pre-write inventory.","observer":"gpt-6.1-sol","exit_code":null,"phase":"manual","scope":"Review-only write boundary","result":"pass","output":"Both target hashes unchanged; six finding rows present; tracked git diff exit 0 with empty output. The only new repository file is the canonical rolling review."}
```

## Out-of-Contract Observations

- **Crash recovery:** a local Windows parent/child probe returned `parent_exited=true, child_still_active=true` after terminating the parent; the reviewer then terminated its disposable child. AC-14 observes failed task state/stale sessions, while AC-29 kills children only on timeout. Consider a simple slot-fencing/human-recovery rule for an orphan after member death so a restarted member does not reuse a still-active slot. Exactly-once execution after forced process death is not an explicit MVP promise, so this is not a blocker.
- **Simplicity:** stdlib, one file, one database, short polling and foreground terminals fit the human's first principle. Stronger byte/content assertions and reusing the existing project-check step fix three blockers without new infrastructure. The unverified POSIX timeout branch can wait for P7 while retaining the executor seam; no required Windows behavior would be lost. No additional broker, scheduler, installer or general sandbox is requested by this review.
- **Later phases:** the versioned envelope, closed executor table, sender policy and artifact references provide additive seams for P4–P7. The execution-authority distinction in F-001 must be settled before enabling agent tasks or member-originated run tasks. No separate ground-up redesign was established from the remaining plan.

## Verdict

**changes_required** — four High blocking findings (F-001–F-004); two Low nonblocking corrections (F-005–F-006). The plan is not ready to execute as written. Corrections belong to `/plan-corrections`; this review does not perform them or start implementation.

**Assumptions and limits:** machine inventory is the supplied handoff state; <member host> was not contacted. Project/tool installation might incidentally supply a missing executable, but the plan must arrange its own prerequisites. The local probes establish observable weaknesses and Windows process behavior only; they do not claim an exploit or failure in nonexistent fleet code. No project suite, live firewall change, pairing or av-kit check was run. Existing red package baselines were read and retained as pre-existing limitations.

**Canonical output:** `P:/agentic-framework/.agent/context/handoffs/2026-11-03-fleet-mvp-plan-critical-review.md`.
Pre-Edit Guard resolved exactly to that path. The only repository write is this review. Receipts and a disposable uncommitted fixture are outside the repository. No plan, product, tool or test was edited, no git commit was created, and neither av-kit nor the local ops folder was mutated. The completion stamp is embedded here to preserve the requested final JSON document.

🕐 Completed: 2026-11-03 21:50 (EST)

## Corrections Applied (2026-11-03)

Applied by the plan author (anthropic) to `implementation-plan.md` and `task.md`. Documents only; no code written. Verdict is `corrections_applied`, not an approval.

Ledger note: the wrapper refused to record the first pass above because its mechanism names were outside `core/.agent/context/review-vocabulary.yaml`. No round was consumed (0/3). The findings above were treated as real and corrected.

| Finding | Correction | Where |
|---------|------------|-------|
| F-001 (AC-8) | New named set `FORBIDDEN_COMMANDS`, refused as any argv's first element at `publish`, at `run` and on the member. "A slot cannot push" removed. The boundary now says what holds and what does not: only the result comes back, nothing reaches <hub host> or GitHub, and project code run by an allowed command can still call those tools (`uv run git` included). Recorded as D-4, `Human-decision-required`, with option A written into the plan. Execution cannot start without the human's ruling (stop condition 9, task row 0). | Named definitions; WP-3 "What `run` is allowed to do"; AC-22, AC-26, AC-28; Decision Log D-4; User Review Required |
| F-002 (AC-5) | The server now asserts zero application bytes after the handshake, for `status` and `pair`, with an oracle check using a client that writes a fake key before checking the pin. | AC-5 |
| F-003 (AC-31) | Old row 12 split. Row 12 writes and publishes the manifest. New human row 13 installs tools on <member host> and restarts the member, proved by new `check_live.py avkit-tools`. Row 14 is the live run. MANIFEST moved to 15, BUILD_PLAN to 16, and references followed. | task.md rows 6, 12-16, H1-1, H1-2, Evidence rules; plan AC-31, stop condition 2, BUILD_PLAN audit, Verification §4 |
| F-004 (AC-23) | Before-and-after path and SHA-256 listing of every fixture file outside `.git`, including ignored files, with an oracle check that overwrites an untracked file. | AC-23 |
| F-005 (Low) | Stop condition 6 separates the temporary `commit-tree` object from a commit that lands work or moves a branch. | Stop conditions |
| F-006 (Low) | `FIREWALL_RULE` defined once. One Firewall checklist holds the command, the reversal, the records, and the Plex and `FPS-SMB-In-TCP` checks. Agent takes the records; the human runs the one elevated command. | Named definitions; Firewall checklist; AC-20; task row 7 |
| Note: AC-9 | Stopped-member fixture ages past a short `--offline-after` before expecting exit 5. | AC-9 |
| Note: `killpg` | POSIX branch removed until P7. | WP-3 run text |
| Note: member death | Stated limitation: a child can outlive a closed member; the restarted member does not look for it, and the human checks. | WP-1 member text |
| Own finding | `AGENT_MODEL_REGISTRY_HOME=P:/.agent` set with `RECEIPTS_DIR`, since the earlier baselines omitted it. | Verification Plan; task Receipts note |

Refuted or deferred: none. D-4 is queued for the human gate as a Decision Brief.

Blast-radius census: 12 values changed, 27 sweeps including variants, receipts in `C:/Temp/agentic-framework/receipts/census-fleet-r1/` (first line of each is an rtk banner).

- **Old values, zero hits (`rc=1`):** "cannot push", "zero HTTP", "request count", "ow 14", "rows 7, 8 and 11", "rows 11 and 12", "AGENTS.md:146", "killpg".
- **Old-value hits, `confirmed-consistent`:** "nothing to push" (plan:404, the new sentence "nothing to push with"); "--timeout 2" (plan:434, AC-29's run timeout, a different value from AC-9's).
- **`updated`:** every `FORBIDDEN_COMMANDS`, `forbidden_command`, "zero bytes", `avkit-tools`, "SHA-256" at AC-23, `Fleet hub 8770`, `the-LAN-subnet`, "AGENTS.md:145", `check_live.py firewall`, `--offline-after` and `AGENT_MODEL_REGISTRY_HOME` hit is a site this correction wrote or a site that repeats it.
- **Variant sweeps, `confirmed-consistent`:** "push" (plan:27, 71, 80, 248, 471, 598, 607; task:17, 79; plan:27 and AC-8 at plan:248 are about what a message can ask for, which D-4 keeps), "sandbox", "publish", "porcelain" (identity at plan:773 and task:40, 65 is a different use), "commit-tree", "POSIX" (plan:393 only).

Verification: `python core/tools/lint_task_contract.py --task docs/execution/plans/2026-11-03-fleet-mvp/task.md` reports OK, 39 rows, 37 fully checked, 2 exempt. av-kit's registered commands were read at `P:/av-kit/.agent/docs/commands.md`: all use `uv` or `npm`, none is in `FORBIDDEN_COMMANDS`.

## Review (2026-11-03, resubmission, ledger round 1)

**Agent:** `gpt-6.1-sol`, the live registry's `independent_reviewer.bindings.codex-cli.slug` (`P:/.agent/model-registry.yaml:660-677`). Author: Claude/Anthropic. **Verdict:** `changes_required`. **Intent achieved:** `partial`.

### Intent Anchor

"Build the MVP of a stdlib-only hub on <hub host> and a pull-only member so that a <hub host> session can run a project's checks on its uncommitted tree on <member host> and get back the exit code, log and tree id, with authority enforced by the hub."

The revised plan can deliver the transport and remote checks, but the human decision still promises isolation that its proposed executor does not enforce. D-4 being pending is not a finding. Its inaccurate assurance is F-001 below.

### Scope

Reviewed both target plan files, the corrections section above, all 27 census receipts in full, the accepted outline, binding fleet handoff, four research files, av-kit line 102 and command registration, local firewall practice, create-plan workflow, plan/task/review templates and the precedent task. P1-P3 are the scope; older drafts do not add requirements. The human's simplicity principle governs recommendations.

The previous submission was refused without consuming a ledger round. This section therefore records **round 1**, as requested, without adding a `## Recheck` heading that would make the legacy Markdown parser count two consumed rounds. Earlier review and correction text is preserved; frontmatter reflects this pass.

| Reviewed input | SHA-256 |
|---|---|
| `implementation-plan.md` | `2d586c89359c26b80e6121f8491b961c2ea0a8aca57193b9152d9b85c9da5ecc` |
| `task.md` | `3901280d62f22072e2efb3bbdd521adb377f0d3872a20408ac2aaba7518b60e4` |

### Findings

All findings have **High confidence**. Short plan/task paths resolve inside `docs/execution/plans/2026-11-03-fleet-mvp/`.

| # | Severity | Blocking | Kind | Finding | File:Line | Recommendation | Status |
|---|---|---|---|---|---|---|---|
| F-001 | High | yes | behavior | **D-4 option A still promises a boundary the design does not provide.** It says nothing a run does reaches <hub host> or GitHub, and reasons that these are kept out of reach. The actual chain is accepted `run` → `execute_run` → project code with the member user's rights and unchanged environment. No network restriction appears anywhere in that chain. An absent `origin` and absent GitHub/signing credentials do not prevent outbound requests or use of any writable network destination already available to that user. An allowed Python program can open a socket; it can also send arbitrary bytes through the member's existing hub connection. AC-28's exact result keys and unchanged <hub host> HEAD/refs establish absence of fleet-managed landing, not confinement of the child or its network effects. A local child-process probe confirmed outbound bytes with `shell=False` and the unchanged environment; it did not test <member host> or establish a successful push. **Violates AC-28's D-4-backed boundary and the binding handoff section 3 authority constraint as represented to the human.** This carries the unresolved assurance from F-001; it does not re-demand prevention of the local commits the corrected limitation explicitly admits. | `implementation-plan.md:80`, `:389`, `:401-410`, `:433`, `:603-609` | State option A as trusted project execution with the member user's filesystem, login and network access; promise only that the fleet does not import or land its changes. Remove the claims that <hub host>/GitHub are unreachable. The human must decide whether that accurately stated trust boundary is acceptable, or whether stronger isolation is required. A stated limitation suffices for the MVP; this finding does not require a sandbox or another mechanism. | open |
| F-007 | Low | no | clerical | **AC-22's template prerequisite is assigned to a later row.** Row 5 runs the AC-22 tests, whose positive contract reads the filled `core/.agent/fleet.json.template`; row 10 first creates that template. The file is a planned output, so its present absence is expected. This is a scheduling correction, not a missing-product finding. | `task.md:45`, `:50`; `implementation-plan.md:427` | Move creation of the existing manifest template into row 5 alongside its validator and AC-22 tests. | open |
| F-008 | Low | no | clerical | **The correction census log does not disposition every receipt hit.** All 27 receipts are untruncated, and all 71 hit lines match the current plan/task. However, the `SHA-256` receipt includes plan lines 184, 281, 338, 696 and 772 in addition to AC-23 at 428; the log dispositions only the SHA-256 hit at AC-23. Those other five hits have no disposition. The protocol's procedural refusal expressly applies on round 2+, whereas this is ledger round 1; this note does not block or replace the substantive review. Subject: `review-scaffolding`. | This review's correction log:169-170; `census-f004-new-sha.txt` | Append `confirmed-consistent` dispositions for those five `implementation-plan.md:<line>` hits and explicitly enumerate the remaining grouped hits so the next resubmission has a complete per-hit record. Preserve the raw receipts. | open |

F-001 and F-007 concern the **deliverable**. F-008 concerns **review-scaffolding**. No finding is classified `control-defeat`: none of the closed vocabulary's three mechanisms describes F-001's execution-boundary claim. There is no invented mechanism id.

### Correction Verification

| Earlier item | Current observation | Disposition |
|---|---|---|
| F-001 | Forbidden first arguments are checked at publish, run and member execution; AC-26 exercises the member boundary with a recording shim. Arbitrary project code calling tools is now explicitly admitted. D-4 is human-gated in row 0 and stop condition 9. Claims of <hub host>/GitHub isolation remain at lines 80, 410, 603 and 609. | Partially corrected; assurance remains open as F-001. Pending human ruling itself is not a defect. |
| F-002 | AC-5 now observes every post-handshake application byte for both status and pair; a fake-key-before-pin client must make the same byte oracle fail. | Fixed in the proposed contract; no fleet TLS implementation exists to execute yet. |
| F-003 | Row 12 publishes, row 13 installs missing project tools on <member host> and restarts the member, `avkit-tools` checks fresh versions, then row 14 runs setup/checks. AC-31 and H1-2 references follow the new sequence. | Fixed; the added human step reuses the existing project bootstrap. |
| F-004 | AC-23 compares path/content SHA-256 identities including ignored files, preserves its index/HEAD/ref checks, and includes a content-corruption oracle mutation. | Fixed; the already-dirty/untracked content false pass is addressed. |
| F-005 | Stop condition 6 explicitly permits the specified temporary `commit-tree` object while retaining the landing/branch/push gate. | Fixed. |
| F-006 | Named `FIREWALL_RULE`, one executable checklist, associated address/port filters, profile comparison, Plex and SMB rule checks; row 7 uses before/after checker modes. | Fixed at plan level. |
| Offline/portability/member-death notes | AC-9 ages the fixture past offline detection; POSIX execution waits for P7; orphan children after member death are an explicit human-recovery limitation. | Addressed without new machinery. |
| Registry baseline correction | Both files set `AGENT_MODEL_REGISTRY_HOME` alongside `RECEIPTS_DIR`; existing red baseline receipts remain distinguished from future fleet failures. | Confirmed. |

### Checklist Results

| Check | Result | Observed evidence |
|---|---|---|
| PR-1 Alignment/order | partial | WP-1 through WP-3 and the revised live rows agree; F-007 is the remaining template-order note. |
| PR-2 Unstarted | pass | All 17 numbered rows, 0-16, are unchecked. Scheduled source/tests/templates/checkers and implementation handoffs are absent, as expected. |
| PR-3 Task contract | pass | Executed linter: 39 rows, 10 columns, 37 fully checked, two source-read exemptions, acyclic dependencies. |
| PR-4 Validation realism | partial | Pin and source-content negatives now falsify their properties. Existing tools exist; future tools are scheduled. AC-28 does not observe the stronger boundary claimed in D-4. |
| PR-5 Source-backed planning | partial | D-1 through D-3 and MVP exclusions follow the accepted outline. D-4 remains an inaccurate decision brief (F-001). |
| PR-6 Correction readiness | partial | 27 raw receipts, 71 hits, no current-text mismatch; incomplete dispositions are F-008. The round-2+ procedural stop does not apply at ledger round 1. |
| PR-7 Scope discipline | pass | P4-P7, internet exposure, additional transports and result landing have source-backed exclusions. No unrelated baseline repair or new sandbox is required. |
| PR-8 Controls/atomicity | partial | HTTP/CLI/member/local chains and observables are named. `Store.tx()` uses per-request `BEGIN IMMEDIATE` for claim/status/pair and the other named decisions; blob replacement is explicit. F-001 limits the boundary these controls establish. |
| PR-9 Single statement | pass | Named state/transition/policy/limit definitions provide the canonical values. The literal firewall command is the executable rendering of its named policy; no conflicting second policy was found. |
| DR-1/4/6 | partial | Most logged corrections match current bytes; D-4's assurance remains unsupported. No implementation-complete claim is accepted. |
| DR-2/3 | n/a | No rename or migration is proposed. |
| DR-5/7/8 | pass | Raw receipts were read, line text was independently compared, statuses and observed exit codes are retained, and runtime limitations are explicit. |

### Acceptance-Criterion Falsification Audit

This assesses the proposed tests, not completed fleet behavior.

| ACs | Assessment |
|---|---|
| AC-1-4 | Missing/extra/type inputs, exhaustive state pairs with unknown-state refusal, real SQL update/delete attempts, and mutated source can fail the intended assertions. |
| AC-5 | Corrected byte-level TLS oracle covers partial traffic and pair as well as status, with an adversarial oracle check. |
| AC-6-8 | Authentication, approval/TTY/name/capacity, sender identity and task-kind negatives have observable refusals and row-count checks. They govern protocol requests; they do not sandbox code admitted under `run`. |
| AC-9-15 | Real subprocess skeleton, concurrent/repeated claim, conflicting/idempotent status, offline/restart/stale-session, secret-pattern and stalled-handshake cases can falsify their contracts. Claimed atomicity is explicit. |
| AC-16-19 | Route enumeration, served-byte hashes, secret-path traversal probes, missing project tools and mutated stop lines have concrete oracles. |
| AC-20-21 | Human rows identify actors, console actions, records and executable follow-up checks. <member host>'s before/after report and unauthorized probe are collected without a new inbound port. |
| AC-22 | Malformed manifests and forbidden first arguments can fail; create its template before row 5's positive test (F-007). |
| AC-23-24 | Snapshot fixture observes captured tree and surviving contents/index/HEAD/ref state; content mutation and bundle failure exercise the negative paths. Filename filtering is limited to the stated likely-secret paths, not general secret detection. |
| AC-25-27 | Real marker/log/tree return, nonzero exit, stop-on-first-failure, refusal sentinels, hash/size and cross-member blob-access tests can fail. |
| AC-28 | Detached/no-remote/cleaned-slot and absent automatic landing are observable. These are not network confinement or a guarantee that arbitrary project code cannot use ambient access (F-001). |
| AC-29-30 | Child timeout sentinel, heartbeat freshness and environment canaries can fail. The separately stated member-death limitation is retained. |
| AC-31 | Corrected tools/install/restart sequence precedes real commands. Rejected/malformed/wrong-tree/leftover-ref results fail; ordinary project test failures may legitimately be returned. |
| AC-32 | New-failure baseline mutation and the final full pytest gate are concrete. AC-name coverage is an inventory check and is not treated as proof of behavior by itself. |

### Durable Evidence

```json
{"schema_version":"evidence.v1","check_id":"r1-resubmission-task-contract","command":"rtk proxy python -B core/tools/lint_task_contract.py --task docs/execution/plans/2026-11-03-fleet-mvp/task.md *> C:/Temp/agentic-framework/receipts/fleet-review-r1-resubmission-task-lint.txt; $reviewLintExit=$LASTEXITCODE; rtk read C:/Temp/agentic-framework/receipts/fleet-review-r1-resubmission-task-lint.txt; exit $reviewLintExit","cwd":"P:/agentic-framework","phase":"static","scope":"Task shape and dependencies","tested_state":"task SHA-256 3901280d62f22072e2efb3bbdd521adb377f0d3872a20408ac2aaba7518b60e4","exit_code":0,"result":"pass","output":"OK: 39 rows; 10-column table; 37 fully checked; dependencies resolve and are acyclic; two view_file exemptions H1-5 and H2-1."}
```

```json
{"schema_version":"evidence.v1","check_id":"r1-resubmission-census","command":null,"procedure":"Read all 27 census receipt files in full. Ran an inline Python audit parsing each docs/path:line:text record and comparing its text with that exact current plan/task line. Compared the correction log dispositions with the complete SHA-256 receipt.","observer":"gpt-6.1-sol","cwd":"P:/agentic-framework","phase":"manual","scope":"PR-6 receipts and dispositions","exit_code":null,"result":"partial","output":"Probe process exit 0: census_files=27; raw_hits=71; current_text_mismatches=[]; SHA-256 sites=[184,281,338,428,696,772]. Only site 428 has an explicit SHA-256 disposition in the correction log. This is ledger round 1, so the workflow's round-2+ procedural refusal is not applied."}
```

```json
{"schema_version":"evidence.v1","check_id":"r1-resubmission-executor-boundary","command":null,"procedure":"Traced run to execute_run and its no-shell, unchanged-environment subprocess contract; compared D-4 and AC-28 with the route table and the binding handoff. Independently started a Python child using subprocess.run with shell=False and no environment override. The child connected to a temporary 127.0.0.1 listener on <hub host> and sent a non-secret canary. Closed the listener after receipt. No <member host> or external endpoint was contacted.","observer":"gpt-6.1-sol","cwd":"P:/agentic-framework","phase":"manual","scope":"F-001: subprocess options do not establish network isolation","exit_code":null,"result":"fail","output":"Probe process exit 0; child_exit=0; receiver obtained UNSIGNED-COMMIT-CANARY. This demonstrates ordinary child network access, not a fleet implementation test, an actual commit, a successful push, or an authenticated writable destination on <hub host>. The plan names no additional producer of the claimed network boundary."}
```

```json
{"schema_version":"evidence.v1","check_id":"r1-resubmission-contract-audit","command":null,"procedure":"Read all 32 ACs and negative tests, task rows and source contracts listed in Scope. Checked scheduled-artifact inventory against file existence, inspected the saved pre-existing refcheck/sanitize baselines, and traced the live human rows and stop conditions. Read the live reviewer binding. Compared each claimed correction with current plan/task text.","observer":"gpt-6.1-sol","cwd":"P:/agentic-framework","phase":"manual","scope":"PR-1 through PR-9 and applicable DR checks","exit_code":null,"result":"partial","output":"17/17 numbered implementation rows unchecked; all planned fleet artifacts absent and scheduled; existing invoked validation tools present. Pin/content/tool-sequence corrections verified. One blocking inaccurate D-4 boundary remains; F-007/F-008 are nonblocking. Saved refcheck has 18 unresolved references and three unclassified tools; sanitize includes pre-existing slug/registry/prose-model/reference failures. These are not fleet regressions. No full product suite or live member/firewall operation was run."}
```

### Simplicity, Later Phases and Limits

- One stdlib file, SQLite, foreground terminals, short polling, full bundles and a persistent detached slot remain appropriate to P1-P3. Correcting the decision brief and moving an existing template require no additional infrastructure. The forbidden-command list is an accidental-use guard; do not expand it into a claimed sandbox.
- The versioned envelope, executor/policy tables, status vocabulary and blob references permit P4-P7 additions. No ground-up redesign is established. Before P6 permits member-originated runs, carry forward the accurately stated trust decision; a sender-kind allowlist cannot confine effects of arbitrary accepted code.
- Human stops for elevation, console pairing/update/tool installation and process startup are executable as described. Orphan children after terminal death remain a stated human-recovery limitation. This review does not require exactly-once execution across process death or a new service.
- No <member host> access, firewall changes, fleet implementation tests or project test suite occurred. A local `shutil.which('npm')` plus `subprocess.run([resolved_npm,'--version'], shell=False)` returned `npm.CMD`, exit 0, version `11.20.0`; Windows command-shim support was therefore not reported as a defect.

### Verdict

**changes_required** — one High blocking finding, F-001, and two Low nonblocking notes, F-007/F-008. D-4 may remain queued for the human after review, but its options must accurately describe what acceptance grants. The human alone can settle whether trusted, unsandboxed execution with ambient member access is acceptable. No additional security machinery is prescribed.

Follow-up is `/plan-corrections` for the inaccurate assurance and the two small notes. This review stops here and does not perform corrections or begin execution.

**Canonical output:** `P:/agentic-framework/.agent/context/handoffs/2026-11-03-fleet-mvp-plan-critical-review.md`.
Pre-Edit Guard resolved exactly to that path. Only this rolling review is edited in the repository; receipts are outside it. No plan/product/tool edits, git commit, av-kit/the local ops folder writes or <member host> contact are authorized or performed by this review.

### Artifact Verification

```json
{"schema_version":"evidence.v1","check_id":"r1-resubmission-artifact-verification","command":null,"procedure":"Ran the review-state-only validator with expected mode plan, exact target and cap 3; preserved its exit. Recomputed both target SHA-256 values against the pre-review receipt. Reconstructed and compared the entire original review body with its saved SHA-256 after the append, restoring its original line endings. Ran git --no-optional-locks diff --exit-code.","observer":"gpt-6.1-sol","cwd":"P:/agentic-framework","phase":"manual","scope":"Review artifact, write scope and history preservation","exit_code":null,"result":"pass","output":"Review parser exit 0: review_mode=plan; round 1 of 3; verdict=changes_required; open findings=4. Its historical findings count does not describe this appended pass: current frontmatter has three findings, of which one blocks. Both target hashes unchanged. Earlier review/correction body exactly preserved, SHA-256 7f1e75a3a4cf6f9af6d2f0554881a7d506599214e23a0f0e9d76a983f0b2d01b. Tracked diff exit 0 with empty output. Final JSON describes only the current pass; no ledger record was attempted by this reviewer."}
```

🕐 Completed: 2026-11-03 22:12 (EST)


## Corrections Applied, second pass (2026-11-03)

Applied by the plan author to the findings in the pass above. Documents only. Verdict is `corrections_applied`, not an approval. **These corrections have had no independent review**: `review_ledger.py` refuses the next round on its token stop, which only a named human can lift.

| Finding | Correction | Where |
|---------|------------|-------|
| F-001 (AC-28) | Option A now reads as trusted project execution with the member user's files, login and network. The claims that nothing reaches <hub host> or GitHub are gone. The fleet promises only that no message can ask for a commit or push and that it imports and lands nothing. The absence of GitHub credentials is stated as a setup fact the fleet does not check. Still D-4, pending the human's ruling. | User Review Required; WP-3 "What `run` is allowed to do"; Decision Log D-4 |
| F-007 (Low) | `core/.agent/fleet.json.template` moved into WP-2 and task row 5, ahead of AC-22's first test. | WP-2 and WP-3 file tables; Work Packages table; task rows 5, 10 |
| F-008 (Low) | Every hit in the first census is dispositioned in the table below, by receipt, with line numbers as they stood in those receipts. | This section |

Blast-radius census for this pass: 2 values changed (the D-4 assurance, the template's row), 10 sweeps, receipts in `C:/Temp/agentic-framework/receipts/census-fleet-r2/`. Old values "reaches <hub host>", "reach <hub host>", "nothing to push" and "own disk" have zero hits. "out of reach" has one hit, plan:82, in the new sentence that says what that depends on: `confirmed-consistent`. "AC-13 reaches it" at plan:256 under the `GitHub` sweep and the `credential` hits at task:100, plan:127, plan:435 are unrelated uses: `confirmed-consistent`. All other hits in those receipts are sites this pass wrote or repeat it: `updated`.

First census, per-hit dispositions (71 hits, 43 `updated`, 28 `confirmed-consistent`):

| Receipt | `updated` | `confirmed-consistent` |
|---------|-----------|------------------------|
| `f001-new-forbidden` | plan:127, plan:399, plan:418, plan:427, plan:431 | none |
| `f001-old-cannot-push` | none (`rc=1`) | none |
| `f001-old-nothing-to-push` | none | plan:404 |
| `f001-var-forbidden` | plan:427, plan:431 | none |
| `f001-var-push` | plan:80, plan:404, plan:409 | plan:27, plan:71, plan:248, plan:471, plan:598, plan:607, task:17, task:79 |
| `f001-var-sandbox` | plan:79, plan:397, plan:410 | none |
| `f002-new-bytes` | plan:245 | none |
| `f002-old-count` | none (`rc=1`) | none |
| `f002-old-http` | none (`rc=1`) | none |
| `f003-new-tools` | task:46, task:53, plan:436, plan:541 | none |
| `f003-old-1112` | none (`rc=1`) | none |
| `f003-old-row14` | none (`rc=1`) | none |
| `f003-old-rows` | none (`rc=1`) | none |
| `f003-var-publish` | task:52, plan:400, plan:418, plan:436, plan:604 | task:45, plan:162, plan:168, plan:294, plan:301, plan:339, plan:357 |
| `f004-new-sha` | plan:428 | plan:184, plan:281, plan:338, plan:696, plan:772 |
| `f004-var-porcelain` | plan:428 | plan:773, task:40, task:65 |
| `f005-commit-tree` | plan:471 | plan:374, plan:443, plan:759 |
| `f006-cidr` | plan:128, plan:312 | none |
| `f006-new-145` | plan:307, plan:341, plan:350, plan:754 | none |
| `f006-old-146` | none (`rc=1`) | none |
| `f006-rule` | plan:128, plan:312, plan:315 | none |
| `f006-var-firewall` | task:47, plan:318, plan:319, plan:341 | none |
| `n1-new-offline` | plan:249 | none |
| `n1-old-timeout` | none | plan:434 |
| `n2-old-killpg` | none (`rc=1`) | none |
| `n2-var-posix` | plan:393 | none |
| `n3-registry` | task:31, plan:508 | none |

Verification: `python core/tools/lint_task_contract.py --task docs/execution/plans/2026-11-03-fleet-mvp/task.md` reports OK, 39 rows, 37 fully checked, 2 exempt.


## Corrections Applied, third pass (2026-11-03)

Applied by the plan author after the human's message, verbatim: "tripple the token budget and add 3 more rounds / both decision recommendations are accepted". Documents only. Verdict stays `corrections_applied`, not an approval.

| Change | Where |
|--------|-------|
| D-4 is `Human-approved`, option A, with the human's message as its reference. "Recommended" and the pending wording are removed; the substance of option A is unchanged. | Decision Log D-4; User Review Required; Spec Sufficiency row; closing Decision Log paragraph |
| The wait for the ruling is removed: stop condition 9 and the first sentence of task row 0. | Stop conditions; task row 0 |
| The review limits line records the grant: 6 plan rounds, 31,500,000 tokens, from `review_ledger.py continue` by the human. | User Review Required |

Blast-radius census: 3 values changed, 9 sweeps, receipts in `C:/Temp/agentic-framework/receipts/census-fleet-r3/`.

- **Old values, zero hits (`rc=1`):** "Human-decision-required", "Recommended", "rules on D-4".
- **"PENDING":** plan:133 (`MAX_PENDING`) and plan:249 (AC-7's pending state) are unrelated: `confirmed-consistent`.
- **"ruling":** plan:612 (D-4 reasoning, history of why it was asked) and plan:753 (outline reference): `confirmed-consistent`.
- **"D-4":** plan:77, 84, 454 and 599 `updated`; plan:399, 438, 450 and 746 `confirmed-consistent` (746 was updated, and states that all four are ruled).
- **"31,500,000" and "Plan loop":** plan:75 `updated`; plan:73 `confirmed-consistent`.
- **"top condition":** plan:466 is the heading, and task:97 refers to the list without naming a count: `confirmed-consistent`. Nothing referred to condition 9 by number.

Verification: `python core/tools/lint_task_contract.py --task docs/execution/plans/2026-11-03-fleet-mvp/task.md` reports OK, 39 rows, 37 fully checked, 2 exempt.


## Recheck (2026-11-03)

**Workflow:** `/plan-critical-review` — resubmission after the third-pass corrections.
**Agent:** `gpt-6.1-sol` (live dispatch registry, `independent_reviewer.codex-cli`).
**Ledger:** `plan-2026-11-03-fleet-mvp`, round **2 of 6**.
**Verdict:** **approved**. **Current findings:** 0, including 0 blocking findings.

### Intent Anchor

"Build the MVP of a stdlib-only hub on <hub host> and a pull-only member so that a <hub host> session can run a project's checks on its uncommitted tree on <member host> and get back the exit code, log and tree id, with authority enforced by the hub."

Executing this plan would deliver that objective within the human's accepted D-4 option A. This approves an unstarted plan; it is not evidence of implemented behavior or permission to begin execution.

### Findings

No remaining or new findings met the materiality threshold. All earlier findings F-001 through F-008 are verified fixed in the proposed contract. Earlier sections remain historical records; their open status cells have not been rewritten.

| # | Severity | Blocking | Kind | Finding | File:Line | Recommendation | Status |
|---|----------|----------|------|---------|-----------|----------------|--------|

### Scope and Confirmed Fixes

Reviewed both target files in full, the outline, binding handoff, all four fleet research files, the create-plan workflow, PLAN/TASK/REVIEW templates, the precedent task, av-kit's branch restriction and registered commands, local firewall practice, closed mechanism vocabulary, live reviewer registry binding, saved red baselines, and all three correction censuses. Sources were read only; no <member host> connection occurred.

References below use `implementation-plan.md` and `task.md` in `docs/execution/plans/2026-11-03-fleet-mvp/`.

| Earlier finding | Independently verified correction | Status |
|---|---|---|
| F-001 — execution authority / inaccurate D-4 assurance | Plan:77-84 and :399-417 explicitly admit ambient filesystem, login and network access, indirect Git/agent invocation, and absence of enforcement of credential absence. D-4:599-613 records the human's accepted option A. AC-22/26 check forbidden first arguments at the real boundaries; AC-28 tests absence of fleet-managed result landing. The obsolete ruling stop is removed from the stop list and task row 0. No sandbox is required or implied. | fixed |
| F-002 — pin oracle | AC-5, plan:247, observes every post-handshake application byte for both `status` and `pair`. Its deliberately premature fake-key write must fail that same oracle. The shared `hub_request` chain checks the pin before writing a request. This addresses partial headers as well as complete requests. | fixed |
| F-003 — av-kit tools before live run | Task:52-54 publish the manifest, stop for <member host>'s project-tool installation and member restart, verify fresh reported tool versions, then run setup/checks. AC-31 at plan:441 and H1-2 at task:59 follow this order. | fixed |
| F-004 — snapshot content preservation | AC-23, plan:433, compares path/content SHA-256 identities including ignored files, alongside the real index, HEAD, porcelain, branch/worktree lists and fleet refs. Its content-corruption oracle distinguishes unchanged porcelain from unchanged contents. The forced bundle failure tests ref cleanup. | fixed |
| F-005 — snapshot commit vs stop condition | Plan:475 expressly permits the temporary `commit-tree` object without granting landing, branch movement or push authority. | fixed |
| F-006 — firewall checklist | Named policy at plan:130; executable creation/reversal and associated address/port filters, profile and Plex/SMB observations at :307-326; AC-20 at :343; task row 7 at task:47. The human performs the elevated change; records precede and follow it. | fixed |
| F-007 — manifest-template order | Plan:361 and task:45 create the template in WP-2 before AC-22's positive test. WP-3 adds the remaining run tests. | fixed |
| F-008 — incomplete census dispositions | The second-pass log inventories all 71 original receipt hits by file/line and disposition. An independent set comparison found no missing or excess dispositions across all 27 original receipts. The second- and third-pass receipts and logs also cover all their hits. | fixed |

The offline fixture ages past its configured offline threshold (AC-9); POSIX timeout implementation waits for P7; orphan children after member-terminal death remain an explicit human-recovery limitation (plan:209-211). The registry-home setting is present in both files. These corrections did not add an unrelated subsystem.

### Checklist Results

| Check | Result | Observed evidence |
|---|---|---|
| PR-1 — alignment/order | pass | WP-1/2/3 and rows 0-16 agree; manifest validation/template precede publication, tool installation precedes live execution, and handoff precedes independent execution review. |
| PR-2 — unstarted | pass | All 17 numbered implementation rows are unchecked. The nine scheduled new fleet source/template/test/checker files and both implementation handoffs are absent as expected. PC/COMMIT are explicitly n/a. |
| PR-3 — task contract | pass | Executed linter returned 0: 39 rows, 10 columns, 37 fully checked, two source-read exemptions, resolving acyclic dependencies. |
| PR-4 — validation realism | pass | Read every AC and negative test; control assertions have observable refusals, rows, bytes, hashes, sentinels or live receipts. All existing invoked tools exist; absent tools are explicit scheduled outputs. No runtime success is inferred from these documents. |
| PR-5 — source-backed planning | pass | D-1 through D-4 match the accepted rulings. A-9 onward identify their refinements and sources. The outline expressly governs over the earlier reference drafts. |
| PR-6 — corrections readiness | pass | Read 27 original receipts / 71 hits, 10 second-pass receipts / 26 hits, and nine third-pass receipts / 16 hits. No truncated census; each hit has a log disposition. Original disposition sets match exactly. Second-pass locations are historical: the third pass changes D-4 wording and shifts lines; those differences were checked against the final text. |
| PR-7 — scope discipline | pass | P4-P7, other transports, result landing, internet exposure and unrelated baseline repair are excluded with sources. No required P1-P3 deliverable is disguised as a deferral. |
| PR-8 — reachability/atomicity | pass | C-HTTP/CLI/MEMBER/LOCAL connect production verbs/routes to named controls and observables. Store.tx uses per-request BEGIN IMMEDIATE for submit/claim/status/pair/approval/revocation/publication; blob replacement is explicit. No missing producer or dead-end control chain was demonstrated. |
| PR-9 — single statement | pass | Canonical state/transition/policy/tool/refusal/limit definitions govern their uses. Concrete test examples and the executable firewall command do not introduce competing policies. No material conflicting definition was found. |
| DR-1/4/6/7 — correction fidelity | pass | Compared each logged correction with current plan/task bytes, including changes introduced by the later passes. The new trust wording removes the previously overstated assurance. |
| DR-2/3 — rename propagation | n/a | No rename or migration is in this scope. |
| DR-5/8 — evidence and limitations | pass | Retained actual linter/ledger exits, receipt census results and target identities; no implementation-complete or live-network claim is made. |

### Negative Tests and Authority Audit

| ACs | Assessment of the proposed contract |
|---|---|
| AC-1-4 | Invalid envelopes, exhaustive/unknown state pairs, direct SQL mutations and mutated source can fail their respective assertions. These are specifications for future tests, not tests run in this review. |
| AC-5-8 | Wrong-pin byte capture includes an adverse oracle check. Missing/wrong/pending/revoked credentials, non-TTY/wrong-code approvals, duplicate names/capacity and prohibited senders/kinds/identities have concrete refusal observations. A member cannot submit work through the named hub task route; no approval HTTP route exists. |
| AC-9-15 | Real hub/member subprocesses, concurrent/repeated claims, conflicting/idempotent statuses, offline/restart/stale-session conditions, secret-pattern inputs, stalled handshakes and oversized JSON can falsify the contracts. The transaction mechanism covers the relevant read-then-write decisions. |
| AC-16-21 | Route enumeration includes every non-open route; traversal probes and served-byte hashes observe bootstrap boundaries. Missing tools, removed stop lines, malformed firewall records and live unauthorized access have named oracles. Human console/elevation/process-start steps are explicit and executable, with the row blocked until the human reports completion. |
| AC-22-24 | Malformed and forbidden manifests fail validation at publish/run/member boundaries. The snapshot fixture observes both what moved and what remained, including ignored contents, index and refs. Secret-path refusal occurs before uploads. Secret-path patterns are a likely-secret filter, not general credential discovery. |
| AC-25-28 | Real marker/log/tree round-trip, nonzero exit, stop-on-first-failure, refusal sentinels, blob hash/size/access checks and detached/remote-free slot observations can fail. AC-28 establishes that the fleet does not return/import a slot commit; D-4 explicitly admits arbitrary effects of trusted project code. |
| AC-29-32 | A delayed child sentinel tests timeout tree-killing; heartbeat freshness and environment canaries test their actual observables. Live av-kit checks reject pre-execution/malformed/wrong-tree results, while ordinary project-check failures may be returned. New-failure baseline mutation can fail package comparison; AC-name discovery alone is not treated as behavioral proof. |

The no-commit/no-push assertion is read at the scope the human accepted: no protocol operation grants either, and the fleet does not land a run's changes. Project code can invoke Git, a signed-in CLI or the network under D-4. The plan states that limitation consistently. This review does not reopen the ruling.

### Commands and Durable Evidence

Executed commands included the following (the inline audits are recorded as manual procedures below because their complete command bodies are not repeated here):

- `rtk proxy python -X utf8 -B core/tools/lint_task_contract.py --task docs/execution/plans/2026-11-03-fleet-mvp/task.md` — exit 0, output below.
- `rtk proxy python -X utf8 -B core/tools/review_ledger.py state --loop-id plan-2026-11-03-fleet-mvp` — exit 0; one recorded round of six, 9,843,670 / 31,500,000 tokens, next round permitted; producer `claude`.
- `rtk proxy git --no-optional-locks status --short` — exit 0; untracked fleet planning/research/review artifacts, with inaccessible global-ignore/cache warnings. This is an inventory observation, not proof of product behavior.
- `rtk read` / `rtk proxy python -X utf8 -B -c ...` — full source reads, line-number extraction, SHA-256 identities, artifact existence, all AC IDs, numbered-row status and raw census/disposition audits.

```json
{"schema_version":"evidence.v1","check_id":"r2-task-contract","command":"rtk proxy python -X utf8 -B core/tools/lint_task_contract.py --task docs/execution/plans/2026-11-03-fleet-mvp/task.md","cwd":"P:/agentic-framework","phase":"static","scope":"Task table and dependency contract","tested_state":"task SHA-256 b33d163c2163906cbab4f988d356aae010dc090062019d941188d70fba8d5bcf","exit_code":0,"result":"pass","output":"OK: 39 row(s); 10-column table (with builder_model); 37 row(s) fully checked: backticked, exit-code re-raised, receipt under RECEIPTS_DIR; dependencies resolve and are acyclic; 2 row(s) exempt (view_file): H1-5, H2-1"}
```

```json
{"schema_version":"evidence.v1","check_id":"r2-corrections-census","command":null,"procedure":"Read all raw census files under census-fleet-r1, census-fleet-r2 and census-fleet-r3, without head truncation. Parsed docs/path:line:text records. Independently compared original receipt file/line sets with each second-pass disposition-table row; no missing or excess entries. Compared every later hit with its log disposition and the final plan/task text, accounting for third-pass line shifts and D-4 edits.","observer":"gpt-6.1-sol","cwd":"P:/agentic-framework","phase":"manual","scope":"PR-6 procedural gate and F-008","exit_code":null,"result":"pass","output":"46 raw receipts, 113 hits total: r1=27/71; r2=10/26; r3=9/16. Original per-hit disposition mismatches=[]. Every third-pass receipt hit matches its current file/line text. Second-pass differences are covered by the third-pass changes. No missing/truncated/undispositioned census."}
```

```json
{"schema_version":"evidence.v1","check_id":"r2-adversarial-plan-audit","command":null,"procedure":"Read both targets and all scoped local sources; trace each control from the named production verb/route to its observable and adverse oracle; inspect Store transaction and blob replacement contracts; compare snapshot before/after observations, human stops, accepted D-4 and P4-P7 extension points. Check scheduled and existing artifact paths, numbered-row states and AC inventory. Read saved refcheck/sanitize red baselines without treating them as fleet regressions.","observer":"gpt-6.1-sol","cwd":"P:/agentic-framework","phase":"manual","scope":"PR-1 through PR-9 and applicable DR checks","tested_state":"plan SHA-256 7966a6427ec1fd8aebc484e5022d281c7e2f5cada030ede321728de45aee437e; task SHA-256 b33d163c2163906cbab4f988d356aae010dc090062019d941188d70fba8d5bcf","exit_code":null,"result":"pass","output":"32 ACs; 17/17 numbered implementation rows unchecked; nine scheduled new fleet artifacts absent as expected; all existing invoked tools present. F-001 through F-008 fixed in the plan contract. No delivery-level blocker or new required subsystem established. No fleet runtime, firewall change or <member host> contact performed."}
```

### Simplicity, Later Phases and Residual Risk

One stdlib file, one SQLite store, foreground terminals, short polling, full bundles and a persistent detached slot are proportionate to this MVP. JSON avoids a parser dependency; TLS and pairing from WP-1 avoid a throwaway localhost transport; git init avoids creating a remote only to remove it. The test harness and two plan-local verifiers prove accepted requirements and do not enlarge the runtime architecture. No additional machinery is requested.

The versioned envelope, named policy/executor tables, status vocabulary and bundle references leave additive seams for P4-P7. Agent adapters/result landing, follow-up turns, member-originated work and non-Windows process control still need their own later-phase contracts. No design point reviewed here establishes a need to rebuild the MVP from the ground up.

Runtime behavior remains unverified because fleet code does not exist yet. Trusted project execution, pattern-based secret detection, unscanned log blobs, retained blobs/objects and possible orphan children are stated limitations. Existing refcheck/sanitize failures remain baseline work outside this MVP. The legacy markdown state parser reads the first historical Findings table; it is not used here as proof that this appended pass has open blockers. The current JSON verdict and this pass's confirmed-fix table identify the current result without rewriting history.

### Verdict and Follow-up

**approved** — the plan would deliver the registered P1-P3 objective under the accepted rulings. There are no open findings and no unresolved human design decision. Execution still waits for the human's explicit proceed instruction, then pauses at the specified human rows. This review stops here.

**Canonical output:** `P:/agentic-framework/.agent/context/handoffs/2026-11-03-fleet-mvp-plan-critical-review.md`.

Pre-Edit Guard resolved exactly to that path. Only its frontmatter verdict/findings_count/round and this appended section are changed in the repository. Earlier text is preserved byte-for-byte. No plan, product or tool edits, git commit, av-kit/the local ops folder write or <member host> contact occurred.

🕐 Completed: 2026-11-03 22:29 (EST)
