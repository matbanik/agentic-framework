---
date: "2026-11-04"
review_mode: "plan"
target_plan: "docs/execution/plans/2026-11-04-fleet-agents/implementation-plan.md"
loop_id: "plan-2026-11-04-fleet-agents"
round: 4
verdict: "approved"
intent_achieved: "yes"
findings_count: 0
template_version: "2.2"
requested_verbosity: "standard"
agent: "gpt-6.1-sol"
---

# Critical Review: 2026-11-04-fleet-agents

> **Review Mode**: `plan`
> **Verdict**: `changes_required`

**Intent anchor:** "Let <hub host> start a Claude or Codex job on another machine with no sign-in there, talk to it while it runs, get its question back, resume it on Mat's words, and land its result on Mat's word, by connecting the credits engine and the dispatch wrappers to the fleet."

Executing this plan as written would not yet deliver that objective: the installed wrappers reject the proposed paths, Codex rejects the proposed resume, and the live sequence cannot update its kit. The gate's token handling and the result commit identity also need correction.

## Scope

**Targets:** `docs/execution/plans/2026-11-04-fleet-agents/implementation-plan.md` and `task.md`. In references below, **plan** and **task** mean those two files.

**Review type:** first-round review of an unstarted execution plan, authored by Claude/Anthropic. **Checklist applied:** PR-1 through PR-9 and the applicable DR checks.

Read the supplied outline's scope, experiment results and D-1 through D-6; the MVP definitions, task shape and call chains; the fleet implementation, bootstrap and test harness; the named credits scripts/schema/probes; both dispatch wrappers; credits state, messaging and inbox code; the installer, manifest, planning templates/workflow and helper precedents. The live registry's `independent_reviewer` binding resolves to `gpt-6.1-sol` for `codex-cli`.

All 43 task rows are unchecked; the implementation handoff and the new product/test/helper deliverables do not exist. Their absence is expected and is not a finding. No remote service, hub or <member host> was contacted. No excluded credential/configuration file was opened. No plan, product, test or tool was edited, and no commit or snapshot commit was created.

## Findings

All findings have **High confidence**. Subjects are `deliverable`; mechanisms are null. The security failure below has no matching mechanism in the supplied closed vocabulary and is therefore reported as `behavior`.

| # | Severity | Blocking | Kind | Finding | File:Line | Recommendation | Status |
|---|----------|----------|------|---------|-----------|----------------|--------|
| F-001 | High | yes | behavior | The shared kit rejects the proposed briefs and Codex slots before a CLI job starts. Violates AC-21 and AC-29. | plan:295; plan:382; plan:466 | Align the filled root/layout and brief locations with the existing wrappers; exercise the installed wrappers with stub CLIs. | open |
| F-002 | High | yes | behavior | Codex inherits `ModelClass=independent_reviewer`; `-NonReviewDispatch` does not make that class resumable. Violates AC-29. | plan:466; plan:509 | Specify a valid non-review Codex execution binding and use it consistently on start/resume. | open |
| F-003 | High | yes | behavior | Row 15's required kit reinstall is refused by the completed Claude run retained from row 12. Its collect/drop implementation arrives later. Violates AC-33. | plan:293; task:55 | Make kit update and retained-result lifetimes compatible, or reorder the work so the prerequisite cleanup is available without losing the required Claude result. | open |
| F-004 | High | yes | behavior | The gate route lacks the scheduled launch's auth scrub and API-key removal, and stdout-only redaction leaves raw probe results in the receipt. Violates AC-15 and its D-1 source. | plan:303; plan:332 | Apply the same child auth hygiene to the gate and check persisted gate artifacts with an echoing fake-token probe. | open |
| F-005 | High | yes | behavior | AC-34 explicitly retains `fleet@fleet.invalid` for newly created snapshot commits, contrary to the user's binding identity rule for every repository. | plan:538; plan:562 | Use `MatBanik <219344396+matbanik@users.noreply.github.com>` for both author and committer and update the planned assertion. | open |
| F-006 | Low | no | clerical | Receipt provenance cites obsolete line locations: Register `:178` and Start `:425` now identify directory checks. | plan:342; plan:814 | Point to `Register-CreditsRun.ps1:261` and `Start-CreditsRun.ps1:209`, preferably with function names. | open |
| F-007 | Low | no | clerical | The bootstrap-stop set is restated after its named definition. | plan:152; plan:584 | Keep the set at `BOOTSTRAP_STOPS` in Named definitions and reference that name in WP-A6. | open |

### F-001 — Production dispatch paths end at existing refusals

The kit is instantiated with `PROJECT_ROOT=<FLEET_HOME>/kit` and `RECEIPTS_DIR=<FLEET_HOME>/receipts`. Briefs are siblings under `agent/<run>/brief-<n>.md`, and slots are under `agent/<run>/slot`.

For Claude, `Start-CreditsRun.ps1:590` passes the brief to `Invoke-ClaudeCredits.ps1`, which forwards `PromptFile` without `RepoRoot` (`Invoke-ClaudeCredits.ps1:259`). `Invoke-ClaudeDispatch.ps1:690` defaults that root to the wrapper's kit directory; `:703-707` accepts a brief only under that repository/worktrees or receipts. The planned brief is under neither. A git-init slot is not a worktree of the kit.

For Codex, `Invoke-CodexDispatch.ps1:965-968` requires `WorkingDirectory` under the filled `PROJECT_ROOT`; the slot is outside it. Its prompt check at `:984-995` independently rejects the brief. WP-A4 schedules only the lock and executable-override changes to this wrapper, so no planned change repairs these refusals. AC-21/AC-29's argv shims can pass while these real checks still reject every job.

Keep the repair small: use accepted locations/root values and test the real installed wrappers with harmless stub executables. A second runner or a general path-bypass mechanism is unnecessary.

### F-002 — Codex execution has no resumable routing contract

The exact planned `CodexRun` call omits `ModelClass`. The wrapper defaults it to `independent_reviewer` (`Invoke-CodexDispatch.ps1:26`). Its early continuation check (`:590-599`) refuses that class even with `-NonReviewDispatch`; this switch only bypasses review-loop accounting. An in-memory rendering of the current wrapper reproduced `resume_refused_review_class`, before registry resolution, receipt access or executable lookup.

The copied live registry also has no `codex-cli` binding for `isolated_worker`, `builder` or `coordinator`; simply adding one of those names to argv is not a working repair. Establish an eligible execution binding as an explicit prerequisite. The default reviewer binding also requires an author vendor, which the top-level planned call does not supply. Do not weaken the review-class resume guard to make an execution call work.

### F-003 — The live sequence cannot reach the Codex gate

`member_kit.py install` must refuse whenever **any** run folder exists (plan:293). Row 12 leaves its Claude run and slot for the final result exercise. Rows 13 and 14 change the kit's task script and Codex wrapper. Row 15 explicitly runs `kit-install` before the Codex and nested-Claude exercises, but the retained run makes that return `runs_present`.

There is no earlier cleanup step: collect/drop are implemented only at row 16 and exercised at row 17. Deleting the earlier Claude result by hand would also defeat the later result demonstration. This is an incompatible lifecycle/order contract, not an objection to a file that the plan intends to create.

### F-004 — The gate has a different secret boundary

The scheduled route explicitly sets `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` and removes `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` (plan:274-277). The gate route only sets `CLAUDE_CODE_OAUTH_TOKEN` (plan:303-306). The actual probes inherit `os.environ` (`probe.py:35,65`; `probe4.py:27`), so absent an unstated parent setting, probe Bash commands/hooks inherit the token. An existing API key can also remain in this route; the plan's scheduled auth test does not cover it.

Separately, `probe.py:72-76` retains CLI `result_text` and `stderr_tail`. `run_gate.py:292-302` writes case results to `gate-result.json` during the run and at completion. Replacing the token in the gate process's printed output afterwards does not sanitize that receipt. The fake-token source probe below produced a passing T2 result containing the fake token. AC-15 currently asks only that an echoing stub's **output** be redacted, so it can pass with the receipt still containing the value. Add receipt/artifact and child-environment assertions to this existing test; no new service is needed.

### F-005 — Snapshot commits are commits under the identity rule

The user requires `MatBanik <219344396+matbanik@users.noreply.github.com>` for commits and tags in every repository. The planned result route calls the existing `make_snapshot`, whose `SNAPSHOT_IDENTITY` explicitly sets both author and committer to `fleet <fleet@fleet.invalid>` (`fleet.py:93-96,1065-1071`). AC-34 positively pins that conflicting identity. A temporary index and a non-branch ref do not change the author/committer recorded in the commit object. No D-1 through D-6 ruling grants an identity exception.

## Checklist Results

These are plan/source observations, not claims that unimplemented acceptance tests passed.

| Check | Result | Evidence |
|-------|--------|----------|
| PR-1 plan/task alignment | partial | Both follow A1-A6; their shared lifecycle has F-003. |
| PR-2 not started | pass | 43 unchecked rows; zero started/completed rows; no implementation handoff or new product/test files. |
| PR-3 task contract | pass | `lint_task_contract.py` exits 0: 43 rows; dependencies resolve and are acyclic. |
| PR-4 validation realism | fail | F-001/F-002 escape the shim tests; F-004 escapes stdout-only redaction. Staged Pester paths and pytest `-k acNN` selections otherwise match the described test names. |
| PR-5 source labels | pass | All 39 ACs have source cells; D-1 through D-6 are preserved as ruled decisions. |
| PR-6 review/corrections readiness | pass | One project handoff and both rolling review paths are explicit. Round-2 census requirement is not applicable. |
| PR-7 scope discipline | partial | Bounded jobs, no live rulings, and other exclusions follow the outline; A-3 states a deliberate hook limitation. The unscheduled `deferred` label is clerical here, not missing accepted A1-A6 work. |
| PR-8 reachable controls | fail | F-001/F-002 trace production paths to real refusals; F-004 demonstrates the unprotected receipt observable. |
| PR-9 single definitions | partial | Named definitions cover the shared sets; F-007 is one repeated bootstrap-stop cluster. |
| DR-1 / DR-7 implementation claims/fresh counts | n/a | This is an unstarted plan, not an implementation handoff. |
| DR-2 / DR-3 terminology and downstream changes | pass | The specific obsolete MVP tests and bootstrap assertions to change are named. |
| DR-4 verification robustness | fail | See F-001, F-002 and F-004. |
| DR-5 evidence auditability | pass | Task commands are concrete and capture/propagate status; the linter independently accepts their shape. |
| DR-6 cross-reference integrity | partial | F-005 conflicts with the current human identity rule; F-006 has stale source anchors. |
| DR-8 limits/completion distinction | pass | The plan states `verified: false`, Codex's messaging limit, token-file access risk, and no full execution-session support. |

### AC and boundary audit

| ACs / surface | Manual review result |
|---------------|----------------------|
| AC-1 to AC-5 | Real write evidence rather than CLI exit is specified; idempotence and both sandbox failures have negative cases. New setup/test/helper files are scheduled. Live S4U evidence remains required. |
| AC-6 to AC-10, AC-12, AC-13 | Cross-field schema, scheduler readback, key-route regression, argv/env and continuation tests have named entrypoints. Existing Interactive pins remain. This does not establish that Limited S4U can register/start tasks; row 8 and stop condition 2 explicitly reserve that experiment. |
| AC-11 | The proposed `check_receipt` project override can work while `check_profile` uses the slot. Absent project settings yield equal `absent` digests for gate and throwaway slot. A present settings file with no hook keys hashes as `{}`, which still differs from `absent`; document that slightly broader limitation if retaining A-3. |
| AC-14 to AC-16 | Installer config keys, including `CREDITS_START_POLICY`, are real. `--verify` checks substitution and install consistency, not wrapper runtime path acceptance. Python-first manifest steps are permitted by `validate_manifest`; `FORBIDDEN_COMMANDS` need not change. F-004 affects the gate; F-003 affects reinstalls. |
| AC-17 to AC-20 | Closed action fields, quote/missing-blob refusals and zero-row observables are specified through the real hub entrypoint. The admitted `Bash(python:*)` limitation is explicit, so no stronger tool sandbox is demanded. |
| AC-21 to AC-25 | F-001 blocks real launches. The generated task path is otherwise what `Read-TaskState` reads; `STOPPED:decision` plus `released:human-gate` maps to `decision`. `credits_state` accepts a stopped-run resume and reuses its expected session; the Claude dispatch continuation checks do not require API-key auth. The planned subscription LaunchHook must also be used on that resumed launch. |
| AC-23 state/export shape | The real run transitions fit the proposed classification, with fail-closed unknowns. `view` exports `class`, `final_status`, `segments` and `outbox`; `Get-CreditsRun -Export` writes the JSON payload, not its formatted console view. Normalization must map `class` and obtain final text from the dispatch artifact. No additional state engine is warranted. |
| AC-26 to AC-28 | The withheld-output oracle and following ping are useful; watch has explicit outcome exits. The end-to-end live stop/resume is required evidence and is not replaced by the shim. |
| AC-29 to AC-33 | F-001/F-002 block real Codex start/resume. Repeated `-Mode` was independently refused. `FullAccessJustification` alone does not select FullAccess; sandbox selection reads `Mode`. Existing output-root checks constrain `OutputDir`, though `-Force` can replace an existing receipt directory inside that root. The file lock is not a hostile-agent isolation boundary; the plan states its bare-Codex limit. F-003 blocks the live update. |
| AC-34 to AC-37 | Temporary-index collection, hash/tree verification, zero-old-value ref creation and no landing commands are specified with meaningful negatives. F-005 concerns identity. Path-only secret detection is already a stated limitation. `collect`/`drop` must reject live segments, including cancellation still being finalized; no fresh remote validation was attempted. |
| AC-38 / AC-39 | Billing wording remains verbatim; bootstrap changes are named. New checkers and tests are scheduled. The baseline comparison intentionally tolerates known refcheck/sanitize failures. Coverage adaptation should scope names to this plan's tests: existing MVP tests already contain ten `test_ac18_*` functions and must not stand in for this plan's quote tests. This is a coverage-map caution, not a claim that the new checker already exists or failed. |

### Observed evidence

```json
{
  "schema_version": "evidence.v1",
  "check_id": "PR-3-task-contract",
  "command": "rtk proxy python core/tools/lint_task_contract.py --task docs/execution/plans/2026-11-04-fleet-agents/task.md",
  "cwd": "P:/agentic-framework",
  "scope": "plan task contract",
  "phase": "static",
  "exit_code": 0,
  "result": "pass",
  "output": "OK: 43 row(s); 10-column table (with builder_model); 41 row(s) fully checked: backticked, exit-code re-raised, receipt under RECEIPTS_DIR; dependencies resolve and are acyclic; 2 row(s) exempt (view_file): H1-5, H2-1"
}
```

The following command renders the wrapper **in memory**, substitutes fixture paths and its script-root expression, and passes it to PowerShell stdin. It reaches the early continuation guard without a registry lookup, CLI invocation, credential access or filesystem write. The Python process reports the child exit explicitly.

```json
{
  "schema_version": "evidence.v1",
  "check_id": "F-002-real-continuation-guard",
  "command": "rtk proxy python -X utf8 -c \"import base64,subprocess;from pathlib import Path; t=Path('core/tools/Invoke-CodexDispatch.ps1').read_text(encoding='utf-8');t=t.replace('{{PROJECT_NAME_UPPER}}','FLEET').replace('{{PROJECT_ROOT}}','C:/review-fixture/kit').replace('{{RECEIPTS_DIR}}','C:/review-fixture/receipts').replace('Split-Path -Parent '+chr(36)+'PSScriptRoot',chr(39)+'C:/review-fixture/kit'+chr(39)); encoded=base64.b64encode(t.encode()).decode(); invoke='& ([scriptblock]::Create([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('+chr(39)+encoded+chr(39)+')))) -Mode ReviewWorkspace -NonReviewDispatch -PromptText review-probe -ResumeDispatchId review-probe';r=subprocess.run(['pwsh','-NoProfile','-NonInteractive','-Command','-'],input=invoke,capture_output=True,text=True,encoding='utf-8');print('child_exit='+str(r.returncode));print((r.stdout+r.stderr).strip())\"",
  "cwd": "P:/agentic-framework",
  "scope": "current Codex wrapper continuation guard, rendered in memory",
  "phase": "targeted",
  "exit_code": 0,
  "result": "pass",
  "output": "child_exit=1\nresume_refused_review_class: class 'independent_reviewer' kind '' loop '' is a review; every review round starts fresh"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "F-004-gate-case-secret-retention",
  "command": "rtk proxy python -X utf8 -c \"import ast,os,subprocess,json; from pathlib import Path; from types import SimpleNamespace; p=Path('core/.agent/skills/claude-credits/probes/probe.py'); fn=next(n for n in ast.parse(p.read_text(encoding='utf-8')).body if isinstance(n,ast.FunctionDef) and n.name=='run_t2'); marker='REVIEW_FAKE_TOKEN'; calls=[]; fakeos=SimpleNamespace(environ={'CLAUDE_CODE_OAUTH_TOKEN':marker,'ANTHROPIC_API_KEY':'REVIEW_FAKE_KEY'}); run=lambda *a,**kw:(calls.append(kw) or SimpleNamespace(returncode=0,stdout=json.dumps({'result':'MANGO-7'}),stderr=marker)); kit=SimpleNamespace(render_settings=lambda c:Path('probe-settings.json'),parse_json_result=json.loads); scope={'Config':object,'Path':Path,'fresh_inbox':lambda *a:Path('fake-inbox'),'post':lambda *a,**k:None,'kit':kit,'os':fakeos,'time':SimpleNamespace(time=lambda:0),'subprocess':SimpleNamespace(run=run),'base_cmd':lambda *a:['stub'],'hook_events':lambda *a:[]}; exec(compile(ast.Module(body=[fn],type_ignores=[]),str(p),'exec'),scope); result=scope['run_t2'](SimpleNamespace(project=Path('.'))); print('probe_child_inherits_token='+str(calls[0]['env'].get('CLAUDE_CODE_OAUTH_TOKEN')==marker));print('probe_child_inherits_api_key='+str('ANTHROPIC_API_KEY' in calls[0]['env']));print('scrub_set='+str(calls[0]['env'].get('CLAUDE_CODE_SUBPROCESS_ENV_SCRUB')=='1'));print('gate_case_result_contains_fake_token='+str(marker in json.dumps(result)));print('case_passed='+str(result['passed']))\"",
  "cwd": "P:/agentic-framework",
  "scope": "real run_t2 function with in-memory fake environment and subprocess; no credential files",
  "phase": "targeted",
  "exit_code": 0,
  "result": "pass",
  "output": "probe_child_inherits_token=True\nprobe_child_inherits_api_key=True\nscrub_set=False\ngate_case_result_contains_fake_token=True\ncase_passed=True"
}
```

```json
{
  "schema_version": "evidence.v1",
  "check_id": "source-and-boundary-trace",
  "command": null,
  "procedure": "Read the plan/task and named sources; follow Register Assert-Receipt at 261 and Start Test-RunReceipt at 209 to run_gate check_receipt at 207 and check_profile at 176; compare installed roots with both dispatch wrappers' physical-path predicates; walk task rows 12 through 17 against runs_present; inspect fleet SNAPSHOT_IDENTITY and commit-tree call; inspect credits_state request/accept/admit/view and Watch Get-RunClass against the generated task and state map.",
  "observer": "gpt-6.1-sol",
  "cwd": "P:/agentic-framework",
  "scope": "PR-1, PR-4 through PR-9 and applicable DR checks",
  "phase": "manual",
  "exit_code": null,
  "result": "fail",
  "output": "Five blocking contract failures, F-001 through F-005, plus two non-blocking clerical findings. No evidence that a new runner or a more elaborate orchestration layer is needed."
}
```

Other read-only probes observed: repeated `-Mode ReviewReadOnly -Mode FullAccess` produces the PowerShell duplicate-parameter refusal; absent settings digest is `absent`, while present `{}` hashes differently; the current working-tree candidate paths and HEAD history have zero `is_secret_path` matches. There are 419 candidate working files totaling 8,531,318 bytes; `git count-objects -v` reports 5,324 KiB loose and 2,338 KiB packed. These sizes show no present size concern, but an exact future snapshot/bundle size was not measured because creating its snapshot commit is outside review authorization.

An initial attempt to invoke the raw template wrapper stopped at its unsubstituted environment-variable syntax, as expected. A first in-memory attempt exceeded the Windows command-line limit; stdin resolved that probe issue. Neither error is a product finding. No pytest/Pester or live acceptance run is claimed.

Reviewed input SHA-256 values:

- `implementation-plan.md`: `66607461012fed89fe80cfce0dc826bd375ef3876a1ab321ec33b06629782684`
- `task.md`: `ab14cbc2dc5694bc451aa428270885a33ff4007c312fa3a7ba97e7d326aca890`

## Out-of-Contract Observations

- AC-13 changes manual `-Continue` selection, although fleet resume calls the scheduler; omit that extra surface if it has no independent caller requirement.
- Keep the accepted local-file access and bare-Codex limitations explicit; this review does not request a new account, broker or sandbox service.

## Verdict

`changes_required` — intent achieved **partial**. Resolve F-001 through F-005 via `/plan-corrections`; retain D-1 through D-6. F-006 and F-007 do not gate approval. The simplicity principle is best served by repairing path/routing and lifecycle contracts around the existing runner.

Residual uncertainty is confined to the declared live experiments: Limited S4U registration/start, the token M-1 gate, scrubbed inbox delivery, actual usage/billing meters, and remote CLI write/resume evidence. The human rows and stop conditions reserve these checks; no remote result was assumed. This review stops here without corrections or execution.

🕐 Completed: 2026-11-04 20:41 (EST)

## Corrections Applied — 2026-11-04

Applied by the plan's author through `/plan-corrections`. This section is not an approval. The round 1 text above is unchanged, and only an independent reviewer can set `approved`.

All seven findings were checked against the code first, and all held.

| Finding | Correction | Where |
|---|---|---|
| F-001 | `PROJECT_ROOT` is filled with `FLEET_HOME`, and briefs move to `receipts/fleet-briefs/<run>/`. No wrapper path check changes. `drop` also deletes the brief folder. New AC-40 runs the real installed wrappers against the member layout, with negatives. | A-13, Named definitions, WP-A2, WP-A3, WP-A4, WP-A5, AC-25, AC-36, AC-40, row 14 |
| F-002 | `CodexRun` passes `CODEX_MODEL_CLASS` (`isolated_worker`) on start and resume, and the review-class resume guard stays. The binding doesn't exist yet, so P-1 goes to Mat and row 3 is held until it is ruled. D-5's remote Claude route stays on the default reviewer class and never resumes. | Named definitions, WP-A4, AC-29, AC-40, Decision Log closing note, stop condition 12, row 3 |
| F-003 | `runs_present` is replaced by `run_active`, read from the task state. Stopped and finished run folders stay. A rename failing on a held file restores the old kit and exits `kit_busy`. | A-15, WP-A2, Atomicity, AC-14, row 15 |
| F-004 | `member_kit.py gate` uses the scheduled route's child environment, then scans every file under `receipts/gate/` and `gate-project/` for the token. A hit deletes them and exits `gate_token_leak`, leaving no receipt. | WP-A2, AC-15, stop condition 7 |
| F-005 | `SNAPSHOT_IDENTITY` is removed. <hub host> uses repo git config, or `identity_missing` if unset. A member reuses the slot HEAD's author. `result` refuses `identity_mismatch` and creates no ref. **Differs from this review's suggestion:** the address stays out of `fleet.py`, because the template is public and git config already holds it. The MVP's `run` route changes too, and row 16 keeps its tests green. | A-14, User Review Required item 7, WP-A5, AC-34, AC-35, the `check_live.py` selftest, row 16 |
| F-006 | Citations now name `Assert-Receipt` at `Register-CreditsRun.ps1:261` and `Test-RunReceipt` at `Start-CreditsRun.ps1:209`. | Spec Sufficiency, A-2 |
| F-007 | WP-A6 refers to `BOOTSTRAP_STOPS` and no longer restates the set. | WP-A6 |

Advisories folded in:

- The `-Continue` change is dropped. AC-13 now covers resume on this route.
- `normalize_view` maps `class` to `stop_class` and reads `final_text` from the latest segment's `final.md`.
- A-2 now states the limit for a hook-free settings file.
- AC-39's coverage is scoped to this plan's own test files.
- A run with a segment whose `finalized_utc` is empty counts as `running`, whatever its state. `cancel` moves a run to `cancelled` before its segment ends, so the state alone would have let `collect` and `drop` through. AC-23 and AC-36 pin this.

**Open human decision:** P-1, in the plan's Decision Log closing note. Option (a) is assumed and not applied. `P:/.agent/model-registry.json` is unchanged.

**Blast-radius census:** 11 values changed, 34 variants swept, 24 old-value sites found, 19 updated, 5 confirmed consistent. Receipts: `receipts/census-fleet-agents-r2/before.txt` and `after.txt`.

**Verification:** `lint_task_contract.py` passes with 43 rows. The resolver check for the binding ran on a scratch copy of the registry. No AC was executed, because every correction is plan text and the tests don't exist yet.

**Ledger:** round 2 is refused on tokens: 11,826,948 spent plus the same reserved, against a budget of 10,500,000. Only a named human can extend it.

Corrected input SHA-256 values:

- `implementation-plan.md`: `cedac92de4f9cc9c6a136b4a4c39295594991ea0f199bed76ea86b804af55359`
- `task.md`: `a6b10650211ebb535b1087b194dfa283c65811f795d5ad8d35b08419ed790b74`

🕐 Completed: 2026-11-04 21:00 (EST)

## Corrections Applied — 2026-11-04, addendum: ruling P-1

Mat first ruled P-1 (a), then changed it to member-only after the author reported that the brief behind that ruling was wrong: any edit to `P:/.agent/model-registry.json` makes the 9 projects with a compiled overlay refuse dispatch with `overlay_not_validated` until each re-syncs. A scratch-copy probe confirmed this for zorivest and av-kit, and the re-sync changes a tracked file in 8 of those repos.

`run_member_setup.py` adds `isolated_worker` on `codex-cli` to the copy it carries to a member, and takes the slug from the reviewer's Codex binding. <hub host>'s file is never written. Changed: User Review Required, `CODEX_MODEL_CLASS`, WP-A1, AC-5, stop condition 12, the Decision Log, and rows 2 and 3. The tracked template is unchanged, because it keeps bindings empty by design (`core/MANIFEST.md:27`).

Token budget extended by Mat to 70,500,000 and recorded in the ledger.

Corrected input SHA-256 values:

- `implementation-plan.md`: `36d8062aaa800d7da88e0ae974e1c6edcf5e805cde9204c72a35157b38726ac0`
- `task.md`: `b3053092f1b3510c180894838a2a2374f5b35f8b5846253f2cb8552ead516a36`

🕐 Completed: 2026-11-04 21:22 (EST)

## Recheck (2026-11-04)

**Workflow:** `/plan-critical-review`, round 2. **Agent:** `gpt-6.1-sol` (the live registry's `independent_reviewer` binding on `codex-cli`). **Verdict:** `changes_required`. **Intent achieved:** `partial`.

**Intent anchor:** "Let <hub host> start a Claude or Codex job on another machine with no sign-in there, talk to it while it runs, get its question back, resume it on Mat's words, and land its result on Mat's word, by connecting the credits engine and the dispatch wrappers to the fleet."

**Scope:** the implementation plan and task file named above, both Corrections Applied sections, both census receipts, and the specified local source contracts. References below use **plan** and **task** for the two target files. This remains an unstarted plan: all 43 task rows are unchecked, and the implementation handoff is absent. Row 0's checkers and later rows' new files are scheduled deliverables, not missing prerequisites.

**Protocol qualification:** PR-6 normally ends a resubmission before substantive review when its census is truncated or lacks per-hit dispositions. Both defects are present here. The user's direct round-2 instruction also explicitly requires verification of every correction and the named new surfaces. This review follows that more specific instruction and records the census defect separately as F-009; it does not pretend that PR-6 passed or use review scaffolding as a delivery blocker.

### Findings

All four findings have **High confidence**, `finding_kind` as shown, and `mechanism: null`. No finding is assigned a mechanism outside the closed vocabulary.

| # | Severity | Blocking | Kind | Finding | File:Line | Recommendation | Status |
|---|----------|----------|------|---------|-----------|----------------|--------|
| F-005 | High | yes | behavior | A-14 still permits a snapshot under the wrong identity before the result check can refuse it. Subject: deliverable. Violates AC-34's global commit identity rule. | plan:574-584; plan:604; plan:980 | Check the approved identity before creating a snapshot; carry/reuse the original <hub host> snapshot's identity rather than trusting the job's mutable HEAD. Refuse a mismatch before `commit-tree`. No literal address in public code is required. | open |
| F-008 | High | yes | behavior | An allowed kit update can strand a retained stopped Claude run: its launcher keeps using the old per-run gate receipt, even after `kit-gate` produces a new one. Subject: deliverable. Violates AC-25's resume contract. | plan:316-322; plan:361; plan:430-431; plan:986 | State and enforce the simple limit that resumable runs must finish before an incompatible update, or explicitly refresh the retained run's receipt through the validated gate route. Keep finished results collectible. | open |
| F-007 | Low | no | clerical | WP-A6's restatement was removed, but A-9 still repeats all three `BOOTSTRAP_STOPS` values. Subject: deliverable. | plan:164; plan:926 | Replace A-9's restated list with the named definition. | open |
| F-009 | Low | no | clerical | The census receipts contain clipped lines and the correction log supplies only aggregate dispositions; `after.txt` also predates the final P-1 ruling. Subject: review-scaffolding. | census before.txt:2-3; after.txt:3,48,87-93; rolling review:228,241-245 | Preserve complete raw sweep lines for the final resubmission and map each old `file:line` to `updated` or `confirmed-consistent` in the existing correction log. | open |

### F-005 — Identity must be checked before the commit exists

The fixed `fleet@fleet.invalid` identity is now explicitly removed throughout the plan. Current git config in this repository is also correct: `MatBanik <219344396+matbanik@users.noreply.github.com>`. That verifies this checkout's present configuration; it does not establish A-14's general claim that reading any repo's config enforces the human's identity rule.

There are two concrete gaps. On <hub host>, nonempty `user.name` and `user.email` are accepted without checking that they are the authorized identity. On a member, plan:576-577 calls the slot's current HEAD "the snapshot <hub host> sent", but an allowed bounded job can create commits in its slot. HEAD then names the job's commit. AC-34 positively requires collection to copy that HEAD's identity, so a job commit with another author makes collection create another wrong-identity commit. `make_snapshot` calls `git commit-tree` before returning a bundle (`fleet.py:1058-1072`); `identity_mismatch` is checked later on <hub host>. It prevents the final result ref but cannot undo the already-created snapshot's author/committer. The check also compares with <hub host>'s current config, which is not necessarily the approved identity.

The fix need not publish Mat's address in `fleet.py`. Resolve and validate the authorized identity before snapshot creation, retain it with the run/base, and use that trusted source on collection. A wrong repo config and a job-created wrong-identity HEAD should both be refused before creating another commit. Retain AC-35's check of job-created history as a separate landing refusal. No real or scratch commit was created during this review.

### F-008 — Re-gating does not replace the receipt the retained run reads

F-003's original failure is repaired: a finished folder no longer prevents row 15's reinstall, and its files remain available for row 17. This finding is a different failure in the newly allowed **stopped-run** case.

The real registration code copies the accepted receipt into `<receipts>/credits/receipts/<run>.gate-result.json` (`Register-CreditsRun.ps1:355-360`). The scheduled task invokes the launcher with `-RunId` only (`CreditsRun.psm1:793`); the launcher defaults to that per-run copy (`Start-CreditsRun.ps1:698-705`). It checks it before accepting a resume (`:431-447`). The member's new gate writes `<receipts>/gate/gate-result.json`, and no proposed change updates the retained copy. Re-registering does not provide an escape: registration refuses a stopped/already-started run (`Register-CreditsRun.ps1:337-340`).

Consequently, after a probe-kit revision or CLI-version change, `kit-gate` can succeed while the retained run still fails `receipt_rejected`. An isolated execution of the real `check_receipt` function with an otherwise valid old receipt and a changed kit revision returned exactly `kit_revision differs from this kit`. Wrapper-only updates need not change that probe-kit revision; this is specifically an incompatible update, not a claim that every reinstall breaks resume.

A stated/enforced update limit is sufficient and simpler than receipt migration: let finished runs wait for collection, and require a resumable run to finish before the incompatible replacement. If resuming across that replacement remains supported, name the small validated receipt-refresh step and exercise it through the existing launcher.

### Prior Pass Summary

| Finding | Prior status | Round 2 result |
|---------|--------------|----------------|
| F-001 | open | **Correction holds.** Root/layout and brief placement satisfy the actual path guards. AC-40 now exercises installed wrappers instead of relying only on argv shims. |
| F-002 | open | **Correction holds.** Every fleet Codex start/resume passes `isolated_worker`; P-1's copied binding resolves without an author-vendor argument. The default review-class resume refusal remains. |
| F-003 | open | **Original correction holds.** Retained finished folders no longer block the row-15 reinstall. The newly allowed stopped-run update has the distinct receipt-lifetime defect F-008. |
| F-004 | open | **Correction holds as a plan contract.** The gate now sets the scrub, removes both API auth variables, scans its persisted outputs, deletes a leaking receipt and refuses. These new functions/tests are not implemented yet. |
| F-005 | open | **Partial; still open.** The wrong fixed identity is removed, but the replacement can propagate another wrong identity before refusal. |
| F-006 | open | **Correction holds.** `Assert-Receipt` really starts at Register:261 and `Test-RunReceipt` at Start:209; both plan citations use those anchors. |
| F-007 | open | **Partial; non-blocking.** WP-A6 uses the name; A-9 still repeats the set. |

### New-surface audit

| Surface | Observation |
|---------|-------------|
| AC-40 / filled root | Codex reads the filled root for its project overlay and working-directory/prompt/schema containment (`Invoke-CodexDispatch.ps1:795,965-995`). `FLEET_HOME` contains the slot and receipt briefs. Claude uses the wrapper's kit directory as its default repo root but independently accepts receipt briefs (`Invoke-ClaudeDispatch.ps1:690-707`). D-5's prompt in the slot is inside Codex's filled root. |
| Other root readers / installer | `instantiate.py:757-801` verifies placeholder removal, credits installation and review limits; it does not require `project_root == --root`. Credits' actual runtime tools derive their code/config root from `PSScriptRoot`/`__file__`, so they still find the kit. Remaining filled-root consumers include the unused POSIX wrapper, preflight/worktree/candidate/benchmark tools and docs; bounded Windows member entrypoints do not call them. A-13 needs no path-check bypass. |
| Path negatives | In-memory rendering of the current wrappers, with real registry logic and equivalent existing-directory geometry, accepted both layouts (child exits 0), refused an outside Codex working directory (1), and refused outside prompt files for both CLIs (1). Codex execution was deliberately stopped after its path/continuation checks, before executable resolution. Claude used `-ValidateOnly`. These are guard probes, not a claim that future AC-40 or installed stub jobs ran. |
| P-1 resolution / overlays | The proposed in-memory registry copy resolved `isolated_worker` on `codex-cli` to `gpt-6.1-sol`, effort `medium`, resolution `default`. The actual unchanged registry refused the unbound class with `unresolvable_on_harness`. No member overlay is shipped by this plan/core. Codex discovers overlays upward from `FLEET_HOME`, Claude from `kit/` (`ModelRegistry.psm1:662-698`); a job's overlay down in its slot is not on either walk. A pre-existing user/ancestor overlay could still refuse dispatch; absence of such an overlay is a setup assumption, not a bypass or a remotely verified fact. No per-member overlay machinery is needed. |
| P-1 AC-5 / stop 12 / limit | AC-5 compares the report's slug with <hub host>'s binding and the registry hash before/after; its specified missing-slug and changed-hash samples cannot satisfy the positive contract. Stop 12 prohibits the <hub host> write and treats a changed hash as a stop. Rows 2/3 schedule the copy-only helper. The limit is accurate: the copied registry stays at its copied binding/catalog until setup runs again. A slug change on setup also remains subject to the wrapper's existing source/target model consistency check on resume. <hub host>'s registry was only read. |
| A-15 / AC-14 | The real scheduler has the named `Running` state, and the plan pins the intended run task paths separately from Monitor. The held-file/failed-verify negatives explicitly require the old kit to remain, not merely a nonzero exit. No installer exists yet to test its rollback. Same-path retained files are coherent for finished results; F-008 covers the unstated limit for resumable ones. |
| AC-15 scan scope / negative | Probe scratch artifacts and rendered settings live under the chosen OUT, and their CLI cwd is the gate project (`probes/kit.py:53-83,112-129,250-255`; `probe.py:35-38,65-76`). Scanning `receipts/gate/` plus `gate-project/` covers these owned artifacts and excludes the canonical token source, avoiding an always-failing self-match. The leaking fake receipt cannot pass the newly required exit/receipt/content assertions; an echo-only stub separately exercises stdout redaction. This does not promise to sanitize arbitrary CLI-managed user files outside those trees. |
| Unfinished segment / AC-23,36 | The actual full view exports `segments[*].finalized_utc`, `dispatch_id` and creation order (`credits_state.py:4065-4091`); Get-CreditsRun exports that JSON payload (`Get-CreditsRun.ps1:313-318`). The unfinished-segment override therefore has its input. Watch waits on normalized `running`, and collect/drop refuse it; no planned consumer still maps cancelled-with-an-open-segment directly to stopped. The credits engine's own state vocabulary is unchanged. |
| `normalize_view.final_text` | The export has no final text field. Latest exported `dispatch_id` resolves the artifact under the existing dispatch output root, and the new prose correctly requires reading its `final.md` and keeping the bounded tail. `class` becomes `stop_class`. No export/schema expansion is needed. |
| AC-13 | Resume now follows Start's actual `-Resume <source>` path (`Start-CreditsRun.ps1:569-575`) and the scheduled hook (`Invoke-ClaudeCredits.ps1:348-354`). The token/scrub test belongs there. The fleet does not use manual `-Continue`, whose key filter is explicitly left alone. |
| Simplicity / ruled scope | Root/brief changes, the existing `isolated_worker` class, gate artifact checks and real-wrapper tests repair demonstrated failures without a second runner. D-1 through D-6 and the final member-only P-1 ruling remain intact. A-14 changes the MVP snapshot route too, as declared and required by the identity rule. A-15 needs the small update limitation or refresh noted above, not a new service. Hooked-project refusal, no Codex mid-run inbox, bare-Codex and local credential-file access limits remain explicit. |

### Census and consistency check

The final plan/task SHA-256 values match the P-1 addendum exactly:

- Plan: `36d8062aaa800d7da88e0ae974e1c6edcf5e805cde9204c72a35157b38726ac0`.
- Task: `b3053092f1b3510c180894838a2a2374f5b35f8b5846253f2cb8552ead516a36`.

Independent reads of the actual receipt bytes found 36 lines in `before.txt` and 122 in `after.txt`. The old lines are clipped at 110 characters (for example before:3 ends `with `); after:3 is clipped at 210 and ends `receipts/fleet-b`. This is truncation in the files, not RTK's presentation. `after.txt` still inventories the superseded global-write/unruled P-1 text, for example after:48 and after:87-93. The correction log's `19 updated, 5 confirmed consistent` at rolling-review:228 does not map those dispositions to the 24 old sites.

Fresh searches of the **current two target files** found zero `runs_present`, `PROJECT_ROOT=<kit>`, `PROJECT_ROOT=<FLEET_HOME>/kit`, `Register-CreditsRun.ps1:178`, `Start-CreditsRun.ps1:425`, `Human decision pending`, or `P-1 is not ruled`. The remaining `fleet.invalid` and `SNAPSHOT_IDENTITY` mentions describe removal/history rather than retaining the old behavior. All brief creation, resume, AC-21/25/40 and drop clauses use `receipts/fleet-briefs/<run>/`. Current P-1 references consistently require a member-only copy and prohibit writing <hub host>'s registry. F-007 identifies the surviving repeated bootstrap set. These fresh observations verify present text; they do not reconstruct the missing per-hit correction audit.

### Checklist Results

| Check | Result | Evidence |
|-------|--------|----------|
| PR-1 plan/task alignment | partial | 40 ACs; rows retain A1-A6 order and include AC-40. Identity/update gaps are F-005/F-008. |
| PR-2 not started | pass | 43 unchecked rows, zero in progress; implementation handoff absent. |
| PR-3 task contract | pass | Linter exits 0, 43 rows, dependencies resolve and are acyclic. |
| PR-4 validation realism / PR-8 reachable controls | partial | Path/routing negatives can fail through real code; no new test executable is assumed present. F-005/F-008 remain delivery gaps. |
| PR-5 source / PR-7 scope | pass | Ruled decisions and previously accepted bounded-job limits retained; no new unscheduled deliverable demanded. |
| PR-6 correction census | fail | Clipped receipts, no per-hit dispositions, final P-1 addendum absent from the after census; direct user scope override explained above. |
| PR-9 single definitions | partial | F-007 remains non-blocking. |
| DR-1,2,3,6,7 | partial | Final input hashes match; old operative terms are gone; census predates final P-1 and A-14's rule claim is too strong. |
| DR-4,5 evidence | partial | Local guard/receipt probes and source chains observed; no future AC/test pass claimed. |
| DR-8 completion vs limits | pass | Plan remains draft; live checks remain human-gated. |

```json
{"schema_version":"evidence.v1","check_id":"R2-task-contract","command":"rtk proxy python core/tools/lint_task_contract.py --task docs/execution/plans/2026-11-04-fleet-agents/task.md","cwd":"P:/agentic-framework","scope":"unstarted task contract","phase":"static","exit_code":0,"result":"pass","output":"OK: 43 row(s); 10-column table (with builder_model); 41 row(s) fully checked: backticked, exit-code re-raised, receipt under RECEIPTS_DIR; dependencies resolve and are acyclic; 2 row(s) exempt (view_file): H1-5, H2-1"}
```

```json
{"schema_version":"evidence.v1","check_id":"R2-production-source-traces","procedure":"Read the plan corrections against both current wrappers, ModelRegistry.psm1, instantiate.verify_only, Register's copied receipt, Start's default Receipt and pre-accept check, check_receipt's version/revision comparison, make_snapshot's commit-tree order, view_run and Get-CreditsRun export. Observe the in-memory guard and resolver probes described in the audit table; no CLI/model was launched. Independently read raw census line lengths and search current targets for obsolete values.","observer":"gpt-6.1-sol","command":null,"cwd":"P:/agentic-framework","scope":"round 2 corrected contracts and their live source dependencies","phase":"targeted","exit_code":null,"result":"partial","output":"Layout guards accept the proposed geometry and reject outside paths; copied binding resolves gpt-6.1-sol/medium and original binding absence refuses; real check_receipt rejects old-revision receipt; export carries finalized_utc/dispatch_id but not final_text; F-005 and F-008 remain."}
```

### Verdict

`changes_required` — the intent is **partial**. F-005 and F-008 require a small contract correction before execution. F-007 and F-009 are non-blocking and do not justify extra review machinery. Resolve through `/plan-corrections`; do not reopen D-1 to D-6 or P-1.

No hub/<member host> contact, credential/token/member configuration read, product/plan/tool edit, or git commit occurred. Only this rolling review was edited. An initial memory-index search under the excluded `.codex` directory was outside the user's requested scope; no credential/auth file was opened and no memory content was used as review evidence. No file in either excluded project was opened. No complete install, S4U task, live billing check or future AC test was run; those remain the named human-gated execution checks. The in-memory probes substitute fixture data and are scoped to the guards/functions stated above.

🕐 Completed: 2026-11-04 21:32 (EST)

## Corrections Applied — 2026-11-04, round 2

Applied by the plan's author through `/plan-corrections`. This section is not an approval. The review text above is unchanged, and only an independent reviewer can set `approved`.

All four findings were checked against the code first, and all held.

| Finding | Correction | Where |
|---|---|---|
| F-005 | `make_snapshot(repo, task, identity=None)` checks the identity before `commit-tree`. On <hub host>, for `agent start` and `run`: the repo's effective config, `identity_missing` if unset, `identity_mismatch` if the address doesn't end with the new constant `SNAPSHOT_EMAIL_SUFFIX`. At member start the received commit is written to `agent/<run>/base`, outside the slot. `collect` uses that commit's author, checks the suffix, and refuses `identity_mismatch` if any commit from `base` to HEAD has another address. The brief says to leave changes uncommitted. `result` keeps its landing refusal and also checks <hub host>'s address. **Stated limit:** snapshots need a GitHub noreply address, which is one constant to change. | User Review item 7, Named definitions, Member paths, outcome reasons, member start step 1, step 3 brief header, A-14, AC-34, AC-35, Files, row 16 |
| F-008 | The review's simpler option, with no receipt migration. `agent resume` of a Claude run first runs the real `run_gate.py --check-receipt` on the run's own receipt, with the same arguments the launcher passes. A failure refuses `receipt_stale`, with no brief written, `stop_gate` unchanged and no task started. The run can still be collected or dropped. **Stated limit:** a stopped Claude run can't resume across a probe-kit or CLI change, including a CLI auto-update. | User Review item 8, outcome reasons, the kit paragraph, `resume`, AC-25, A-15 |
| F-007 | A-9 names `BOOTSTRAP_STOPS` and no longer restates the set. | A-9 |
| F-009 | The receipts below are unclipped, and `after.txt` postdates every edit, including P-1. Each old site is mapped below. | This section |

Code read while correcting, beyond what the findings cite:

- `make_snapshot`'s only production caller is `fleet.py:1091`. The two test callers at `test_fleet_run.py:149,319` keep their form because `identity` defaults to the repo's config.
- `COMMITTER` at `test_fleet_run.py:716` commits in a `run` slot, and that route never calls `collect`, so it stays.
- `Test-RunReceipt` at `Start-CreditsRun.ps1:209-215` passes the manifest's `project_root`, `python_exe` and `claude_exe`. `check_profile` reads the slot, so the pre-check passes the slot and `gate_project`, not `gate_project` alone.
- `test_fleet_run.py` doesn't isolate global git config, so AC-34's "no `user.email`" case sets `GIT_CONFIG_GLOBAL` to an empty file. Otherwise the machine's own address would hide the refusal.

**Round 2 census.** Terms: the 13 in `before.txt`, plus `SNAPSHOT_EMAIL_SUFFIX`, `BOOTSTRAP_STOPS`, `agent/<run>/base` and `P-1` in `after.txt`. Receipts: `receipts/census-fleet-agents-r3/before.txt` (57 lines) and `after.txt` (100 lines), neither clipped. `receipt_rejected` has no hit in either, by design: it stays the launcher's own reason. Old line numbers are from `before.txt`, and `updated` means the text at that site changed.

| Old site | Term | Disposition | Now at |
|---|---|---|---|
| task:56 | `make_snapshot`, `SNAPSHOT_IDENTITY` | updated | task:56 |
| plan:110 | `fleet.invalid` | confirmed-consistent, describes removal | plan:110 |
| plan:111 | `user.email` | updated | plan:111 |
| plan:164 | `browser-approval` | confirmed-consistent, the one definition | plan:170 |
| plan:184 | `identity_missing` | confirmed-consistent | plan:191 |
| plan:185 | `identity_mismatch` | confirmed-consistent; both codes also added to outcome reasons at plan:196 | plan:192 |
| plan:312, plan:392, plan:846 | `kit-gate` | confirmed-consistent | plan:320, plan:401, plan:865 |
| plan:322 | `kit-gate` | updated | plan:330 |
| plan:401 | `make_snapshot` | confirmed-consistent | plan:410 |
| plan:574, plan:575, plan:576 | `make_snapshot`, `SNAPSHOT_IDENTITY`, `identity_missing`, `user.email`, `slot's HEAD` | updated | plan:588-594 |
| plan:579 | `make_snapshot` | confirmed-consistent | plan:597 |
| plan:583 | `identity_mismatch`, `base` | confirmed-consistent | plan:601 |
| plan:584 | `user.email` | updated | plan:602 |
| plan:585 | `base` | confirmed-consistent | plan:603 |
| plan:604 | AC-34, all its terms | updated | plan:622 |
| plan:605 | AC-35, `identity_mismatch`, `base` | updated | plan:623 |
| plan:622 | `make_snapshot`, `SNAPSHOT_IDENTITY` | updated | plan:640 |
| plan:926 | `browser-approval` | updated | plan:945 |
| plan:973 | `fleet.invalid` | confirmed-consistent, A-14's question | plan:992 |
| plan:976 | `SNAPSHOT_IDENTITY`, `slot HEAD` | updated | plan:995 |
| task:48, task:55 | `kit-gate` | confirmed-consistent. Row 15 runs on row 12's finished run, which `receipt_stale` doesn't touch | task:48, task:55 |
| task:40, task:59, plan:648, plan:655, plan:686, plan:750, plan:1035 | `base`, as "baseline" | confirmed-consistent, unrelated word | task:40, task:59, plan:667, plan:674, plan:705, plan:769, plan:1054 |

**Round 1 census, the 24 sites behind the earlier aggregate.** Line numbers are from `receipts/census-fleet-agents-r2/before.txt`, which stays clipped. Each disposition was read against the current text, not reconstructed from the old `after.txt`, and shows the site's state after round 1 and P-1 together.

| Old site | Term | Disposition |
|---|---|---|
| plan:293, plan:331 | `runs_present` | updated to `run_active` |
| plan:167, plan:382, plan:397, plan:435 | `brief-<n>` | updated to `receipts/fleet-briefs/<run>/` |
| plan:539, plan:562 | `SNAPSHOT_IDENTITY`, `fleet.invalid` | updated, and changed again this round |
| plan:606 | AC-39 | updated, coverage scoped to this plan's test files |
| task:40 | `AC_COUNT` | updated to 40 |
| task:59 | AC-39 | confirmed-consistent |
| plan:295 | `PROJECT_ROOT` | updated to `<FLEET_HOME>` |
| plan:280 | `-Continue` | updated, the change is dropped |
| plan:330 | `-Continue`, AC-13 | updated, AC-13 now covers resume |
| plan:353 | `-Continue` Files row | updated, it now reads `-Subscription -TokenFile`, hook |
| plan:356, task:44 | AC-13 | confirmed-consistent |
| plan:207, task:43 | `model-registry` | updated by the P-1 ruling, member copy only |
| plan:342, plan:814 | `Register-CreditsRun.ps1:178`, `Start-CreditsRun.ps1:425` | updated to the `Assert-Receipt` and `Test-RunReceipt` citations |
| plan:152 | `browser-approval` | confirmed-consistent, the one definition |
| plan:584 | `browser-approval` | updated, WP-A6 names the constant |
| plan:882 | `browser-approval` | updated, in this round's F-007 correction |

**Verification:** `lint_task_contract.py` passes with 43 rows. `P:/.agent/model-registry.json` still hashes to `7097dc5bb0f07978...`. No AC was executed, because every correction is plan text and the tests don't exist yet.

**Ledger:** 22,152,917 of 70,500,000 tokens spent, 2 of 3 rounds used, and the next round is permitted. Round 3 is the last.

Corrected input SHA-256 values:

- `implementation-plan.md`: `6226bd267a9dcffb4967b74e4ef647eb5762630182acd8f7db72a473a7f59ffe`
- `task.md`: `a6a38036c1bc3bca499401029cc5fd35c7146501cb34d6b5c19d2afd678671ba`

🕐 Completed: 2026-11-04 21:41 (EST)

## Recheck (2026-11-04) — Round 3, final permitted round

**Workflow:** `/plan-critical-review`. **Agent:** `gpt-6.1-sol`, independently checked against the dispatch registry's `independent_reviewer` / `codex-cli` binding. **Verdict:** `changes_required`. **Intent achieved:** `partial`.

**Intent anchor:** "Let <hub host> start a Claude or Codex job on another machine with no sign-in there, talk to it while it runs, get its question back, resume it on Mat's words, and land its result on Mat's word, by connecting the credits engine and the dispatch wrappers to the fleet."

**Scope:** the two supplied plan files, the round-2 correction section above, both round-3 census receipts, the outline's ruled scope, and the relevant live fleet, test, credits, wrapper, registry, installer and planning contracts. Below, **plan** and **task** identify the implementation plan and task file in `docs/execution/plans/2026-11-04-fleet-agents/`. This is an unstarted execution plan: 43 task rows are unchecked, no task status is in progress, and the implementation handoff is absent. New files scheduled in row 0 and rows 1–18 are not missing prerequisites.

### Findings

Both findings have **High confidence**, subject `deliverable`, kind `behavior`, and `mechanism: null`. Neither fits a mechanism in the closed vocabulary. F-005 carries forward the unresolved authorized-identity requirement; F-010 concerns a distinct sequencing failure introduced by applying the new collector to retained runs.

| # | Severity | Blocking | Kind | Finding | File:Line | Recommendation | Status |
|---|----------|----------|------|---------|-----------|----------------|--------|
| F-005 | High | yes | behavior | The suffix check still permits snapshots under another owner's identity, on <hub host>, through `run`, and then on collection. It does not enforce the binding identity rule cited by AC-34. | plan:185; plan:588–595; plan:622; plan:999 | Validate the authorized author and committer identity before `commit-tree`; keep configuration-based resolution if desired, but do not equate a noreply suffix with the approved identity. | open |
| F-010 | High | yes | behavior | Row 16 introduces the snapshot identity change after rows 12 and 15 have created the runs retained for row 17. Their saved bases still carry the old fixed identity, which the new collector must reject. This prevents the required two live results from landing. Violates AC-37. | task:48,52,55–57; plan:422; plan:593–595; plan:625; `.agent/fleet/fleet.py:93–95,1065,1071` | Move the snapshot identity change and its necessary fixture adjustment before the first live snapshot route in row 8, so rows 12 and 15 create collectable bases. Preserve the simple retained-run sequence; no migration mechanism is needed. | open |

### F-005 — Address form is still not authorization

The correction fixes the timing: plan:590 explicitly checks before `commit-tree`, and plan:593 replaces the mutable HEAD identity with the saved base identity. It also checks job-created author and committer addresses before collection. Those are real improvements.

The remaining failure is in the accepted value. `SNAPSHOT_EMAIL_SUFFIX` at plan:185 accepts every address ending in `@users.noreply.github.com`. A nonempty, different `user.name` and a different owner's noreply address satisfy plan:591–592. The new snapshot then exists under that different identity. `run` explicitly shares this rule; collection reuses that accepted base's author, and `result` compares against the same <hub host> configuration, so none of those later checks rejects the case. Even the approved address with an incorrect name passes the stated validation.

The human's binding rule specifies `MatBanik <219344396+matbanik@users.noreply.github.com>` for commits and tags in every repository. No D-1–D-6 or P-1 ruling relaxes it. Plan:999's assertion that checking only the address form "holds the same rule" is therefore false. This remains F-005, rather than a new, deeper mutation of a repaired control. A small identity comparison suffices; this finding does not require a new identity service or publishing an owner's address in reusable product code.

### F-010 — The corrected collector rejects the plan's own earlier runs

The live source still sets the fixed snapshot author and committer at `.agent/fleet/fleet.py:93–95`; `make_snapshot` injects them at :1065 before `commit-tree` at :1071. The only current production caller is `cmd_run` at :1091. Plan:410 makes the new `agent start` use that same function. Task:56 explicitly schedules removing `SNAPSHOT_IDENTITY` and checking the address in **row 16**, not in the earlier agent-start row.

Row 12 must already start and resume a Claude job (task:52). Row 15 must already run the Codex job, and explicitly keeps row 12's finished run for row 17 (task:55). Member start records the received snapshot commit as `base` (plan:421–422). Thus both retained bases were created by the pre-row-16 fixed-identity producer. Updating the member at row 17 changes code, not those historical commit objects. The new collector must reject their base address under plan:593–595. The rejection follows from the declared row order and current producer; it does not require a live experiment to establish it.

This is different from F-003's retained-folder install refusal and F-008's retained-receipt lifetime. Both of those corrections can hold while this sequence still fails. Moving the small identity change earlier also avoids emitting old-identity `run` snapshots during row 8's kit install/gate steps. Re-running all jobs after row 16 or migrating their bases would add avoidable work.

### Prior Pass Summary — Independent correction verification

| Finding | Round 3 result | Evidence |
|---------|----------------|----------|
| F-005 | **Partial; still open.** Pre-commit timing, the saved base, and pre-collection history checks are now specified. The permitted identity remains too broad. | plan:110–115,185,421–427,588–595,622–623,995–999. Live snapshot order: `fleet.py:1058–1079`. F-010 separately records the newly exposed live-row sequencing problem. |
| F-007 | **Correction holds.** A-9 now names `BOOTSTRAP_STOPS`; the operative three-value definition occurs only at Named definitions. | plan:170,646,666,940–949. Old `browser-approval` sites are dispositioned at rolling-review:392,406,429–431. The live constant is expected to change during execution. |
| F-008 | **Correction holds as a plan contract.** A-15 chooses the permitted simple limitation rather than receipt migration. Claude resume pre-checks the retained receipt before changing the brief, task state or scheduler. | plan:116–119,314–318,330–331,440–445,482,1000–1009. Live receipt copy: `Register-CreditsRun.ps1:355–360`; launcher default/check: `Start-CreditsRun.ps1:703–704,444–447`. Runtime qualifications appear below. |
| F-009 | **Correction holds.** Both receipts are complete, the after census matches the final input, and the log maps every old site. PR-6 passes. | `census-fleet-agents-r3/before.txt`: 57 lines, 44 hits, 33 unique sites; `after.txt`: 100 lines, 83 hits, 61 unique sites. Every after hit equals the current source line. Rolling-review:389–410 covers all 33 old sites, including grouped sites; :416–431 supplies the older 24-site map. |

The plan/task SHA-256 values independently match rolling-review:439–440 exactly. The raw receipts contain lines up to 1,930 characters; the files themselves are not clipped. All 13 before-term headings and 17 after-term headings are present, including zero-hit terms. A fresh literal union search finds no missing or extra after sites. `receipt_rejected` and `slot HEAD` have zero hits in both target files; the former deliberately remains the launcher's reason. Remaining `fleet.invalid` and `SNAPSHOT_IDENTITY` mentions describe removal/history. The surviving `slot's HEAD` at plan:593 explains why it is unsafe to trust it. No operative clause still says to copy HEAD's identity. The obsolete root, `runs_present`, unruled P-1 and pending-human-decision literals also have zero hits. New suffix, base and stale-receipt clauses agree with one another; their substantive defects are the findings above, not census drift.

### New-surface audit and runtime limits

| Surface | Verified conclusion and limit |
|---------|-------------------------------|
| Saved base, retained run and resume | Plan:187,421–422 creates the base outside the slot; plan:444–445 keeps the same slot on resume; install keeps run folders outside `kit/` (plan:324–331). The current fetch path retains `refs/fleet/task/<task_id>` at `fleet.py:1254–1255` and detaches HEAD at :1257. Ordinary HEAD movement does not change the saved OID or that retained ref. Sharing this fetch path therefore provides a reachable source through normal retention/resume; new implementation is still required. |
| History rewriting and trust | A hash in an external file is not itself a Git reachability root or a security boundary. A job that also deletes the retained refs and prunes objects can destroy the referenced object; a job able to edit member metadata can replace the file. The plan specifies no tamper isolation, and its same-user limits already acknowledge arbitrary code/file access (plan:130–135). No such destructive job or future collector was executed here. Classify missing-object handling, deliberate metadata tampering and collection after destructive history rewriting as **runtime/unverified residual risks**, not demonstrated new delivery blockers. A stated bounded-job limitation is sufficient; this review does not demand a separate protected store. |
| Identity negatives | AC-34 now has observable failure: no new commit object and no uploaded blob for missing/non-noreply configuration or a differently addressed job commit. `GIT_CONFIG_GLOBAL` isolation prevents a global address hiding the missing-local-address case (plan:622). AC-35 checks no result ref on mismatch (plan:623). Those negatives can fail; they simply omit the different-owner noreply/name case in F-005. The job's already-existing adversary commit is part of the pre-collection baseline, not an object that collection can undo. |
| Existing MVP callers/tests | The scoped source sweep finds only the current production caller `fleet.py:1091` and test callers `test_fleet_run.py:149,319`. Their argument forms survive the optional identity parameter. Their repos use `new_repo` at :107–117, so changing its email fixture at :111 covers those calls and the `run_task` tests. `COMMITTER` at :712–717 runs inside the member's `run` slot and never enters `collect`; the plan correctly leaves it alone. Other credits tests using similarly spelled fixture addresses do not call `make_snapshot`. No additional definite suffix regression was found. Preserve the existing `no_head` refusal at `test_fleet_run.py:293–300` by retaining HEAD validation before any identity failure for an empty repo; "before commit-tree" does not require changing that order. Future test execution remains necessary. |
| Pre-check arguments and CLI selection | `Test-RunReceipt` currently passes `--project` from `manifest.project_root` and `--python` / `--claude` from `launch` (`Start-CreditsRun.ps1:212–215`). Plan:314–318 adds conditional `--gate-project` to both production receipt checks, and :440–443 uses those same values for the fleet pre-check. `check_profile` still measures the slot (`run_gate.py:176–204`); passing only the gate project would be wrong, but the corrected plan does not do that. The new flag and pre-check are planned changes, not existing live features. |
| Claude only | Plan:440 explicitly restricts this pre-check to a Claude resume. Codex handlers are selected from the saved `cli` (plan:519–522), and their resume remains the existing dispatch continuation path (plan:511–515). There is no planned Claude receipt prerequisite on a Codex resume. |
| Pre-check success followed by `receipt_rejected` | **Still possible**, for example a CLI auto-update between the two checks. The launcher independently re-checks before accepting the request (`Start-CreditsRun.ps1:431–447`); `run_gate.py:227–236` reads the installed version, current probe revision and launch profile anew. An isolated execution of the real `check_receipt` function with fixture producers returned success, then a version mismatch after the version producer changed. The early check is a useful refusal, not an atomic promise about a later launch. No serialization service is needed. |
| Refused run cleanup | A `receipt_stale` refusal precedes brief/stop-gate/request mutation (plan:443–444), leaving a stopped run collectable and then droppable under AC-34/36. A late launcher rejection initially leaves a pending request: the start caller times it out (`Start-CreditsRunTask.ps1:239–252`), and the store restores `previous_state` (`credits_state.py:1522–1528`). Cleanup is therefore not necessarily immediate during that interval. The new handlers and complete stale-resume → collect → drop sequence have not run; AC-25 explicitly tests collection, and AC-36 separately governs dropping. Neither claim overrides identity refusal, as F-010 demonstrates. |
| Limit accuracy | The retained per-run receipt is not replaced by re-gating, so an incompatible probe-kit or Claude CLI version change, including auto-update, prevents resume. `kit_revision` hashes the probe `.py` files (`probes/kit.py:137–143`), not every installed wrapper. Receipt checks also compare interpreter and hook settings (`run_gate.py:176–204`); unchanged version/revision is not a blanket waiver of those checks. Finished-result collection does not use the receipt check. |
| Row 12 → row 15 and ruled scope | `receipt_stale` does not itself break this order: row 12 must finish, row 15 retains that finished run, and only later new runs need the refreshed gate. F-010 is the separate identity-order defect. D-1–D-6 and final member-only P-1 remain faithfully carried forward at plan:121–126,235–239,706,1010–1027. No <hub host> registry edit, overlay rollout, new runner or receipt migration is requested. The correction's suffix restriction changes the existing `run` route as disclosed; disclosure does not supersede the global identity rule. |

### Checklist Results

| Check | Result | Evidence |
|-------|--------|----------|
| PR-1 alignment / PR-4 realism / PR-8 reachability | partial | Source traces establish both blockers. Pre-commit and receipt negatives now name real observables; future functions/tests remain unimplemented. |
| PR-2 not started | pass | 43 unchecked task statuses, zero in-progress statuses; implementation handoff absent. |
| PR-3 task contract | pass | Task linter exits 0; dependencies resolve and are acyclic. This structural pass does not detect F-010's semantic prerequisite. |
| PR-5 source / PR-7 scope | partial | Ruled scope and bounded-job limits retained. F-005 contradicts the global identity rule cited by AC-34. The already-evidenced bounded-job deferral does not justify another blocker over its label. |
| PR-6 census / DR-1,2,3,5,7 | pass | Complete raw receipts, all old-site dispositions, exact after-line match, matching final hashes; correction content judged independently above. |
| PR-9 definitions / DR-6 consistency | partial | F-007 fixed; new literals agree. F-005 is a substantive rule mismatch rather than stale spelling. |
| DR-4 negative oracles / DR-8 limits | partial | Described negatives can fail; no future AC, complete CLI run, S4U job or live billing check was executed. Runtime-only uncertainties are stated above. |

```json
{"schema_version":"evidence.v1","check_id":"R3-task-contract","command":"rtk proxy python core/tools/lint_task_contract.py --task docs/execution/plans/2026-11-04-fleet-agents/task.md","cwd":"P:/agentic-framework","scope":"unstarted task contract","phase":"static","exit_code":0,"result":"pass","output":"OK: 43 row(s); 10-column table (with builder_model); 41 row(s) fully checked: backticked, exit-code re-raised, receipt under RECEIPTS_DIR; dependencies resolve and are acyclic; 2 row(s) exempt (view_file): H1-5, H2-1"}
```

```json
{"schema_version":"evidence.v1","check_id":"R3-correction-audit","command":null,"procedure":"Independently inspect all raw before/after receipt lines and the per-site correction tables; compare each after file:line payload to the current target text and compare its site set to a fresh literal union search. Read the cited production snapshot producer and task order, receipt copy/default/check and timeout restoration paths. Compare the proposed suffix predicate with the human's exact identity rule. Observe the isolated current check_receipt probe with fixture receipt/profile/version producers; no real CLI or credential source is consulted.","observer":"gpt-6.1-sol","cwd":"P:/agentic-framework","scope":"F-005, F-007, F-008, F-009 and corrected A-14/A-15","phase":"targeted","exit_code":null,"result":"partial","output":"Census: before 57 lines/33 sites, after 100 lines/61 sites, no missing/extra sites or after payload mismatches; hashes match correction log. Different-owner noreply passes suffix; old fixed snapshot identity fails it. Current check_receipt accepts fixture, rejects old revision, and rejects changed CLI version on a later call. F-005 remains; F-010 exposes incompatible retained bases from pre-row-16 starts."}
```

### Verdict and stop

`changes_required` — intent is **partial**. F-005 still permits the wrong authorized identity, and F-010 prevents the specified retained live results from being collected. F-007, F-008 and F-009 hold as described above. This is **round 3 of 3**: stop the bounded review loop here and report the result to Mat; do not schedule another review round or autonomously start corrections. The concrete repairs are an authorized-identity comparison and moving the snapshot identity work before the first live snapshots, without reopening any ruled decision.

No hub or <member host> contact, credential/token/member configuration read, product/plan/tool edit, scratch commit or git commit occurred. Only this canonical rolling review was edited. An initial memory-index search accessed a file under the excluded home `.codex` directory; that access was outside the requested scope. None of that file's contents is used or reproduced as review evidence. No file in either excluded project was opened. The AST probe stubbed the profile/version producers and is not a full receipt-gate or future implementation test. The local timestamp skill path named by the workflow is absent; the completion time below was obtained from the clock tool. The user's final JSON contract takes precedence over the workflow's prose timestamp suffix.

🕐 Completed: 2026-11-04 21:46 (EST)

## Corrections Applied — 2026-11-04, round 3

Applied by the plan's author through `/plan-corrections`, after the round cap's hard stop and Mat's answer: "c, P-2 recommended, 2 more rounds". This section is not an approval. The review text above is unchanged, and only an independent reviewer can set `approved`.

Both findings were checked against the code and the task order first, and both held. F-010 came from the author's own F-005 correction.

| Finding | Correction | Where |
|---|---|---|
| F-005 | **Ruling P-2.** New `snapshot_identity(repo)`: the repo's effective `user.name` and `user.email` must equal the global git config, and the address must end with `SNAPSHOT_EMAIL_SUFFIX`. Either value unset at either level → `identity_missing`. A difference or a failed suffix → `identity_mismatch`. It runs after `no_head` and before `commit-tree`, and `result` uses it too. Collection compares names as well as addresses. New AC-41 holds the <hub host> cases, including another person's noreply address and a different name. **Stated limit:** a global config changed to another noreply address passes. | User Review item 7, Named definitions, Commit identity, `result`, AC-34, AC-35, AC-37's selftest, AC-41, Spec Sufficiency, A-14, P-2, Decision Log closing note, row 0 (`AC_COUNT` 41) |
| F-010 | New row 7a builds <hub host>'s half before row 8, the first live snapshot. Rows 12 and 15 therefore create collectable bases, and no migration is needed. Row 16 keeps `collect`, `drop`, `result` and the member's half. AC-34 gains the negative for a `base` under the old identity. | Row 7a, row 8's dependency, row 16, Work Packages table, the Order paragraph, A-14 |

Code read while correcting:

- `test_fleet_run.py:107-117`: `new_repo` sets repo-level config only, and no test isolates global config. Under P-2, the fixture repo's values would differ from the machine's, so an autouse fixture points `GIT_CONFIG_GLOBAL` at a temporary file holding the same fixture identity. Row 7a runs that file in full.
- `test_fleet_agent.py` is created at row 1, so AC-41's test has a home before row 7a.
- Read-only check of all 33 repos under `P:/`: each one's effective name and address equal the global values, and the global address passes the suffix check. The check printed no address.

**Census.** Receipts: `receipts/census-fleet-agents-r4/before.txt` (81 lines) and `after.txt` (117 lines), neither clipped. `after.txt` adds `snapshot_identity` and `row 7a`. Old line numbers are from `before.txt`, and `updated` means the text at that site changed.

| Old site | Disposition | Now at |
|---|---|---|
| plan:110 | confirmed-consistent, describes removal | plan:110 |
| plan:111, plan:112, plan:113 | updated | plan:111-115 |
| plan:185 | confirmed-consistent | plan:186 |
| plan:191, plan:192, plan:196 | confirmed-consistent | plan:193, plan:194, plan:198 |
| plan:372, plan:696 | confirmed-consistent, row 8's number is unchanged | plan:374, plan:704 |
| plan:410, plan:422 | confirmed-consistent | plan:412, plan:424 |
| plan:588, plan:591, plan:592, plan:593, plan:594 | updated | plan:590-600 |
| plan:597 | confirmed-consistent | plan:603 |
| plan:601, plan:602 | updated | plan:607, plan:608 |
| plan:622, plan:623, plan:625 | updated (AC-34, AC-35, AC-37) | plan:629, plan:630, plan:632 |
| plan:634 | updated | plan:642 |
| plan:640 | confirmed-consistent, still a WP-A5 file | plan:648 |
| plan:641 | updated | plan:649 |
| plan:667, plan:754 | confirmed-consistent | plan:675, plan:762 |
| plan:990, plan:992 | confirmed-consistent | plan:998, plan:1000 |
| plan:995, plan:999 | updated | plan:1003, plan:1007 |
| task:40 | updated, `AC_COUNT` 41 | task:40 |
| task:56 | updated, and its identity work moved to row 7a | task:57, task:48 |
| task:63 | confirmed-consistent | task:64 |
| task:82 | confirmed-consistent | task:83 |

Row 8's dependency, not a census term, moved from 7 to 7a at task:49.

**Verification:** `lint_task_contract.py` passes with 44 rows. `P:/.agent/model-registry.json` still hashes to `7097dc5bb0f07978...`. No AC was executed, because every correction is plan text and the tests don't exist yet.

**Ledger:** Mat granted 2 more rounds, recorded with their words. 3 of 5 rounds used and 25,959,300 of 70,500,000 tokens spent, and the next round is permitted.

Corrected input SHA-256 values:

- `implementation-plan.md`: `66c4a8f4b62724c7b783563e73319443c795dee602a8b5ee8c935a1616d3823b`
- `task.md`: `f323cb86cd1ac8536fb6073b06ff8885218c97f02ffd88141f4a0d886ed751fd`

🕐 Completed: 2026-11-04 21:57 (EST)

## Recheck (2026-11-04) — Round 4 of 5

**Workflow:** `/plan-critical-review`. **Agent:** `gpt-6.1-sol`, checked against the dispatch registry's `independent_reviewer` / `codex-cli` binding. **Verdict:** `approved`. **Intent achieved:** `yes`, as an implementation plan; no implementation or live acceptance is claimed.

**Intent anchor:** "Let <hub host> start a Claude or Codex job on another machine with no sign-in there, talk to it while it runs, get its question back, resume it on Mat's words, and land its result on Mat's word, by connecting the credits engine and the dispatch wrappers to the fleet."

**Scope:** both supplied plan files; Corrections Applied — 2026-11-04, round 3; the two raw round-4 census receipts; the outline's ruled scope; relevant live fleet producer, caller, tests and harness; credits, dispatch, registry, installer and planning contracts. Below, **plan** and **task** mean the two files in `docs/execution/plans/2026-11-04-fleet-agents/`. All 44 task statuses remain unchecked, `scripts/tests/test_fleet_agent.py` is absent as expected before row 1, and the implementation handoff is absent. This remains plan review.

### Findings

F-011 has **High confidence**, subject `deliverable`, kind `clerical`, `mechanism: null`, and is non-blocking under the workflow's Materiality Gate. There is no remaining evidence-backed High/Critical delivery blocker.

| # | Severity | Blocking | Kind | Finding | File:Line | Recommendation | Status |
|---|----------|----------|------|---------|-----------|----------------|--------|
| F-011 | Low | no | clerical | Row 7a changes the snapshot author to the configured fixture identity and runs the whole MVP run suite, but that suite still asserts the old literal author name `fleet`. The correction inventory names the fixture address/global-config changes without naming this old expectation. | `scripts/tests/test_fleet_run.py:110,239`; task:48; plan:633,649 | Include the routine update of the author expectation at line 239 to the configured fixture name in row 7a. Keep the assertion on the produced commit. | open |

The new expected name is trivially determined by AC-41 and the existing `new_repo` fixture. This is a stale test literal, not an ambiguous identity design or a reason to spend another review round. It would make the unadjusted assertion fail after implementation; the future suite was not run here.

### Prior Pass Summary — Independent correction verification

| Finding | Prior status | Round 4 result |
|---------|--------------|----------------|
| F-005 | open | **Correction holds as ruled by P-2.** Plan:187 now requires both effective repository values to equal their global counterparts, with missing-value and suffix refusals. Plan:590–593 applies it before `commit-tree` on `run` and `agent start`; plan:606–609 applies the same resolver to `result`. Plan:600–601 and AC-34/35 compare names and addresses. AC-41 includes a different owner's noreply address and a different name. The limitation appears at plan:114–115 and :1049–1051. This closes the prior suffix-only defect under the human's new ruling; it does not claim the future implementation already exists. |
| F-010 | open | **Correction holds.** Task:48 builds <hub host>'s producer in row 7a and task:49 depends on it. The live producer still injects the old constant at `.agent/fleet/fleet.py:1065` before `commit-tree` at :1071, and `cmd_run` calls it at :1091. Moving this change before row 8 therefore repairs the actual producer used for the first live kit snapshots and the later retained bases. Row 16 now explicitly retains the member half, collect/drop and result, at task:57. |

### Census and consistency

The complete receipts are `C:/Temp/agentic-framework/receipts/census-fleet-agents-r4/before.txt` and `after.txt`. An independent parser read every line, checked each after payload against the indicated current file and line, and recomputed the literal union over both targets. The correction map at this review's lines 550–571 covers all **36 unique old sites**, including its grouped entries.

| Observation | Result |
|-------------|--------|
| Before receipt | 81 lines; 19 term headings; 62 hits; 36 unique sites |
| After receipt | 117 lines; 21 term headings; 96 hits; 48 unique sites |
| Completeness/freshness | Maximum line length 1,930 characters; no after payload mismatch; no missing or extra union-search site; zero-hit headings retained |
| Plan SHA-256 | `66c4a8f4b62724c7b783563e73319443c795dee602a8b5ee8c935a1616d3823b` |
| Task SHA-256 | `f323cb86cd1ac8536fb6073b06ff8885218c97f02ffd88141f4a0d886ed751fd` |

Both hashes match the author's final input hashes. The surviving `fleet.invalid` and `SNAPSHOT_IDENTITY` mentions describe removal, the historical defect or its negative fixture (plan:110,590,629,633,648,1000,1003; task:48). No operative clause retains the suffix-only <hub host> check. A fresh scan for row-16/identity combinations finds only task:57's correctly retained **member** half; plan:63,595–597,1003 and task:48–49 consistently put <hub host>'s work in row 7a. `row 16` itself has zero literal census hits. No stale promise to defer <hub host>'s change to row 16 was found. F-011 is in live test source outside the plan-only census.

### New-surface audit and execution limits

| Surface | Verified conclusion and limit |
|---------|-------------------------------|
| P-2 faithfulness | The named definition, operative identity paragraph, result paragraph, AC-41 and Decision Log agree (plan:187,590–608,633,1029–1051). `None` selects the resolver for both <hub host> snapshot callers; the member explicitly supplies the saved base identity (plan:591,599–604). This preserves P-2's small config comparison without an identity registry or a published owner address. |
| Effective config and `includeIf` | P-2 deliberately compares configuration, not an immutable person. A repository's effective values must include applicable config overrides; a different effective identity must fail against the selected global reference. Conditional global includes can make that reference depend on repository context, and `GIT_CONFIG_GLOBAL` can select another file without editing the usual global file. These are forms of the disclosed mutable-global-authority limitation, not grounds to reopen the ruling. A read-only Git config probe on stdin demonstrated conditional inclusion: the same matching `includeIf` returned `core.autocrlf=false` with `--no-includes` and `true` with `--includes`. It used the installed Git system config, not a credential file. The future resolver's exact global/include command choices are **implementation verification**, since there is no resolver on disk yet. |
| Environment route to commit identity | Checking `user.*` alone does **not** control Git's actual author/committer. A read-only `git var` probe with fixture values left `git config --get user.email` at the fixture address while all four `GIT_AUTHOR_*`/`GIT_COMMITTER_*` overrides changed the reported identities. No commit was created. The live producer currently prevents inherited identity overrides through `{**os.environ, **SNAPSHOT_IDENTITY, ...}` at `fleet.py:1065`, passed to `commit-tree` at :1071. Its planned replacement must preserve that binding with the resolved/provided pair; AC-41 already requires actual author **and** committer equality, rather than merely a resolver return. Whether the new code does so is **runtime/unverified implementation risk**, not a demonstrated plan failure. Reusing the existing four-variable assignment needs no additional machinery. |
| Explicit member identity | `collect` intentionally does not ask a member's own git config for authority. It takes the saved base's author, rejects an invalid base suffix and different job author/committer names or addresses before snapshotting (plan:599–604,629). This explicit-argument path is necessary for the stated member model. `result` independently compares subsequent commits to <hub host>'s checked identity (plan:606–609,630). No current alternate production snapshot caller was found beyond `cmd_run`; the two new callers are expressly specified. Deliberate same-user replacement of the saved base remains the previously stated trust limitation, not a new protected-store requirement. |
| Can AC-41's negatives fail? | Yes as specified observables: missing global name/email even with local values; missing effective values when neither source supplies them; different noreply addresses; same address/different name; matching non-noreply values; and an empty repository's `no_head` (plan:633). Commit-object count, refs and hub blobs distinguish a pre-commit refusal from a late refusal or upload. Removing only a local value while the global still supplies it does **not** create a missing-effective-config case; that follows the ruled effective-config definition. These future negatives have not executed. |
| Global fixture's other effects | The current `new_repo` sets local identity and `commit.gpgsign=false` (`test_fleet_run.py:107–116`); the slot COMMITTER explicitly passes its identity and `--no-gpg-sign` (:712–717). A read-only comparison using `GIT_CONFIG_GLOBAL=/dev/null` observed the real global `commit.gpgsign=true` disappear, while system `core.autocrlf=true`, `core.symlinks=true` and `init.defaultBranch=main` remained. The fixture therefore does not erase system config. No concrete dependency on the removed global signing settings was found in these tests, including the member's slot commit. This does not prove every future fixture implementation or subprocess lifetime is correct. |
| Rig process lifetime | `rig` is module-scoped and starts its member at `test_fleet_run.py:175–188`; `Member.start` copies the current environment at `fleet_harness.py:103–108`, as does `run_cli` at :40–44. A function-scoped autouse fixture need not precede the module-scoped rig, and a member started while a temporary config is active keeps that path after the parent changes it. The proposed fixture has no implementation yet. Scope/file lifetime and the complete existing run suite, explicitly selected by task:48, are **runtime/unverified**; there is no demonstrated member regression to rate as a blocker. |
| Row 3 versus first snapshot | Task:43 runs setup and member update through the local helper/WinRM route, not `fleet run`; outline:22 likewise distinguishes the earlier S4U experiments from a fleet task. The existing update script fetches/hash-checks the bootstrap `fleet.py` (`docs/execution/plans/2026-11-03-fleet-mvp/scripts/<member host>-update.ps1:1–13`). Row 8 is the first declared live snapshot route (task:49; plan:322–323). Row 7a is therefore early enough. |
| Rows 9–16 and test visibility | Row 1 creates `test_fleet_agent.py` (task:41), so row 7a's `-k ac41` can see its new test. Rows 9–11 then add hub/agent/watch, row 12 creates the retained Claude run, rows 13–14 add Codex and its lock, row 15 creates the Codex run while retaining Claude, and row 16 adds collection/result (task:50–57). These dependencies remain coherent. The pre-existing whole-suite `fleet` author expectation is F-011. |
| Simplicity and ruled scope | The correction adds one shared identity resolver, reuses the current producer with an optional identity argument, and moves its <hub host> portion earlier. No extra live job, migration, overlay rollout, protected identity store, runner or hub route is introduced. D-1–D-6 remain aligned with outline:49–62,72–77,114–118,149–153,180–185,212–216,241–246. Member-only P-1 stays at plan:237–241,1023–1028. P-2's reference-config limitation is disclosed. No correction silently changes the member-only binding or bounded-job scope. |

### Checklist Results

| Check | Result | Evidence |
|-------|--------|----------|
| PR-1 plan/task alignment; PR-3 task contract | pass | Manual dependency trace above; task linter exits 0 with 44 rows and acyclic dependencies |
| PR-2 not started | pass | 44 unchecked statuses; no implementation handoff; planned agent test absent |
| PR-4 validation realism; PR-8 control reachability | pass for plan contract | Actual snapshot producer traced; negative observables are discriminating; task:48 runs AC-41 and the full MVP run suite. No future test execution claimed |
| PR-5 sources; PR-7 scope | pass on corrected surface | Human-ruled P-2 governs F-005; D/P decisions and prior evidenced bounded-job limits retained |
| PR-6 census; DR-1,2,3,5,7 | pass | Complete receipt parsing, all old-site dispositions, exact after payloads and final hashes |
| PR-9 definitions; DR-6 consistency | pass with note | Resolver/refusals/order agree across plan and task; stale live test literal is F-011 |
| DR-4 robustness; DR-8 limits | partial | Read-only Git probes establish distinct config/identity inputs; future resolver, fixture and live jobs remain unexecuted |

```json
{"schema_version":"evidence.v1","check_id":"R4-task-contract","command":"rtk proxy python core/tools/lint_task_contract.py --task docs/execution/plans/2026-11-04-fleet-agents/task.md","cwd":"P:/agentic-framework","scope":"unstarted task contract","phase":"static","exit_code":0,"result":"pass","output":"OK: 44 row(s); 10-column table (with builder_model); 42 row(s) fully checked: backticked, exit-code re-raised, receipt under RECEIPTS_DIR; dependencies resolve and are acyclic; 2 row(s) exempt (view_file): H1-5, H2-1"}
```

```json
{"schema_version":"evidence.v1","check_id":"R4-correction-audit","command":null,"procedure":"Parse every line of the two census receipts; verify all 36 old sites against the correction map, every after payload against the current line, and the after site set against a fresh literal union. Hash both target files. Read the cited producer/callers, task dependencies, fixture helpers and rig environment propagation. Compare the revised clauses with P-2 and the outline's ruled scope.","observer":"gpt-6.1-sol","cwd":"P:/agentic-framework","scope":"F-005, F-010 and round-3 corrections","phase":"static","exit_code":null,"result":"pass","output":"Before: 81 lines/62 hits/36 sites; after: 117 lines/96 hits/48 sites; no missing or extra sites and no payload mismatches; both hashes match. Both prior corrections hold as plan contracts. F-011 is a non-blocking stale live-test author expectation."}
```

```json
{"schema_version":"evidence.v1","check_id":"R4-git-input-probes","command":null,"procedure":"Observe subprocess Git probes run through rtk proxy python -X utf8 -c: isolate config using /dev/null and fixture -c user.name/user.email values; compare git config --get user.email with git var GIT_AUTHOR_IDENT/GIT_COMMITTER_IDENT before and after fixture author/committer environment overrides. Parse a stdin config with a matching includeIf pointing to the installed Git system config, once with --no-includes and once with --includes; preserve repository access with -c safe.directory=P:/agentic-framework. Compare selected non-secret effective settings with and without the usual global config. Execute no commit-tree, commit, hub or member command.","observer":"gpt-6.1-sol","cwd":"P:/agentic-framework","scope":"Git config versus actual identity; include semantics; proposed fixture side effects","phase":"targeted","exit_code":null,"result":"partial","output":"Successful probes exited 0: user.email stayed fixture@users.noreply.github.com while author/committer became other@users.noreply.github.com; conditional include changed autocrlf false to true; hiding the usual global config removed global signing=true but preserved the observed system settings. These are Git-input probes, not executions of the planned resolver or fixture."}
```

### Verdict and stop

`approved` — the corrected plan is capable of delivering the registered intent within the human's ruled limits. F-005 and F-010 are closed **for this unstarted plan**. F-011 is a routine stale expectation to update during row 7a; the environment-binding, conditional-global and fixture-lifetime points above remain explicitly classified implementation verification. They do not establish another delivery blocker or justify additional machinery. Approval does not authorize execution: plan:75–76 and task:15–17 still require Mat's proceed instruction.

Only this canonical review was edited, with earlier body text preserved and frontmatter advanced. No memory search, excluded project/directory access, token/credential/member-config read, hub/<member host> contact, product/plan/tool change, scratch commit or repository commit occurred. The workflow was re-read before closeout. Its local timestamp skill path is absent; the time below comes from the clock tool. The requested v2 final JSON takes precedence over the workflow's older prose-only final shape and its obsolete empty-findings-on-approval clause.

🕐 Completed: 2026-11-04 22:06 (EST)

## Corrections Applied — 2026-11-04, round 4

Applied by the plan's author through `/plan-corrections`. This section is not an approval. The review text above is unchanged, and only an independent reviewer can set `approved`.

**The Round 4 verdict above was not recorded.** The wrapper's schema validation refused it: `checklist_results/4/result: 'partial' is not one of ['pass', 'n/a']`. An `approved` verdict can't carry a `partial` check. The ledger has no round 4 and still reads 3 of 5. The author changed this file's frontmatter verdict from `approved` to `corrections_applied` so that the file doesn't claim an approval the ledger doesn't hold. The author didn't edit the reviewer's `final.json` or call `record` by hand.

That dispatch's usage isn't in the ledger either: `events.jsonl` reports 3,335,400 input and 22,084 output tokens, so the ledger's total understates real spend by about 3.36M.

The finding and two points from that section were checked against the code, and all three held.

| Item | Correction | Where |
|---|---|---|
| F-011 | `test_fleet_run.py:239` asserts the author `fleet`, which row 7a removes. Row 7a changes the assertion to the fixture name, and it stays an assertion on the produced commit. | task:48, plan:650 |
| Fixture lifetime (the section's "Rig process lifetime") | `rig` at `test_fleet_run.py:175` is module-scoped, and `Member.start` copies the environment. The fixture is now module-scoped and autouse, so it is in place before `rig` starts its member and for as long as that member runs. | task:48, plan:650 |
| Identity variables (the section's "Environment route to commit identity") | The plan didn't say the checked identity is bound to the commit. It now says the name and address go into all four `GIT_AUTHOR_*` and `GIT_COMMITTER_*` variables, as `fleet.py:1065` does today. AC-41 now requires the repo's identity on the commit even when the environment sets those variables to other values. | plan:594, plan:634 |

**Census.** Receipts: `receipts/census-fleet-agents-r5/before.txt` (22 lines) and `after.txt` (29 lines), neither clipped. `:239` and `%an` have no hit in `before.txt`. `rig` was searched for, and its only hit is new.

| Old site | Disposition | Now at |
|---|---|---|
| task:48 | updated | task:48 |
| task:57 | confirmed-consistent | task:57 |
| plan:590 | confirmed-consistent | plan:590 |
| plan:633 | updated | plan:634 |
| plan:648 | confirmed-consistent | plan:649 |
| plan:649 | updated | plan:650 |
| plan:675, plan:762 | confirmed-consistent | plan:676, plan:763 |
| plan:1003 | confirmed-consistent | plan:1004 |

New site: plan:594, the new sentence.

**Verification:** `lint_task_contract.py` passes with 44 rows. `P:/.agent/model-registry.json` still hashes to `7097dc5bb0f07978...`. No AC was executed, because every correction is plan text and the tests don't exist yet.

Corrected input SHA-256 values:

- `implementation-plan.md`: `770def7baf8f7fd10de9faa8b04b5a1238b0074247da0fdb7e6d540ae1524aa7`
- `task.md`: `594e8a62f0725c37fe9bbeb18cb5ae977915bfbb9b9c6fb7da0b1ae58e84508f`

🕐 Completed: 2026-11-04 22:13 (EST)

---

## Resubmission (2026-11-04) — Round 4 of 5

**Workflow:** /plan-critical-review  
**Agent:** gpt-6.1-sol (live registry: independent_reviewer / codex-cli)  
**Scope:** implementation-plan.md and task.md in docs/execution/plans/2026-11-04-fleet-agents/, checked against the outline, MVP contracts and the cited live fleet, test, credits, dispatch and packaging sources.

**Intent anchor:** "Let <hub host> start a Claude or Codex job on another machine with no sign-in there, talk to it while it runs, get its question back, resume it on Mat's words, and land its result on Mat's word, by connecting the credits engine and the dispatch wrappers to the fleet."

This is an independent replacement for the unrecorded round-4 dispatch, not another ledger round. The earlier round-4 section was a lead only. This section uses a different heading so it does not add a fifth round to the Markdown recheck counter. Intent achieved: **yes, as an unstarted execution plan**, within the ruled limits.

### Findings

No remaining evidence-backed findings. No new machinery or additional plan correction is required.

| # | Severity | Blocking | Kind | Finding | File:Line | Recommendation | Status |
|---|----------|----------|------|---------|-----------|----------------|--------|

### Prior Pass Summary — Independently Confirmed Corrections

References below use plan and task for the two review targets.

| Item | Result | Evidence and reasoning |
|---|---|---|
| F-011 | Fixed in the plan contract | The live helper configures the name fixture at scripts/tests/test_fleet_run.py:110; its produced-commit assertion still expects fleet at :239. Plan:650 and task:48 now explicitly change that assertion to the fixture name while retaining the assertion on the commit. Unchanged implementation source is expected at this stage. |
| Fixture lifetime | Correction holds as a design | rig is module-scoped at test_fleet_run.py:175, starts its member at :185 and closes it at :188. Member.start copies os.environ into the subprocess at scripts/tests/fleet_harness.py:103-108; Hub.close kills and waits for child processes at :181-185. Plan:650 now puts the global-config file and environment setting in a module-scoped autouse fixture before rig and keeps them alive for its lifetime. This matches both the parent and member lifetimes. |
| Identity variables | Correction holds in the specification | Plan:594 binds the checked name/email to all four author/committer variables. The live producer already overlays four values onto os.environ at .agent/fleet/fleet.py:93-96,1065 and passes that env to commit-tree at :1071. The correction changes the source of those four values, preserving the binding. AC-41 at plan:634 now asserts the actual commit identity with conflicting inherited values. |
| F-005 | Still fixed under the human's P-2 ruling | Plan:187 defines equality of both effective repository values with their global counterparts plus the noreply suffix, with missing/mismatch refusals. Plan:590-594 applies the resolver before commit-tree on <hub host>'s run and agent start. Plan:607-610 applies it to result; AC-34/35/41 name the corresponding negative observables. Plan:1050-1052 expressly states the mutable-global limitation. This is faithful to P-2, not a renewed suffix-only rule. |
| F-010 | Still fixed | task:48 builds <hub host>'s snapshot change in row 7a; task:49 makes the first live snapshot row depend on 7a. The actual retained producer is cmd_run -> make_snapshot at fleet.py:1086-1092. Plan:596-598 prohibits earlier starts, task:53,56 retains the two later runs, and task:57 leaves member collection/result work in row 16. No migration or extra runner is necessary. |

### Census and Evidence Freshness

Independently parsed both raw r5 census receipts and compared every after payload with the current file. Before: **22 lines, 13 hits, 9 distinct sites**. After: **29 lines, 20 hits, 10 distinct sites**. All nine before sites have dispositions in the correction log at :690-699; the new site is plan:594. A fresh union of the nine searched patterns yields exactly the after sites: no missing/extra site and no payload mismatch. Empty sections for the old :239, %an and rig searches are visible, not clipped output.

Current SHA-256 values match the author's corrected inputs:

- implementation-plan.md: 770def7baf8f7fd10de9faa8b04b5a1238b0074247da0fdb7e6d540ae1524aa7
- task.md: 594e8a62f0725c37fe9bbeb18cb5ae977915bfbb9b9c6fb7da0b1ae58e84508f

### Adversarial Audit and Limits

| Surface | Observed conclusion |
|---|---|
| Module fixture versus AC-41 | The proposed autouse fixture belongs to test_fleet_run.py (plan:650). AC-41 belongs to the separate test_fleet_agent.py (plan:651), and each of its tests selects its own GIT_CONFIG_GLOBAL file (plan:634). A module-local fixture does not govern that separate module merely because it imports a helper. Per-test environment changes do not rewrite an already started member's environment; the MVP member retains its module fixture path. The fixture must use module-compatible resources and restore its environment after rig teardown. No fixture implementation exists yet, so actual dependency scope, restoration and combined-suite isolation are execution checks. |
| Can the environment case fail? | Yes as a specified oracle: plan:634 checks author and committer on the produced commit, not merely config or env names. A producer that lets inherited wrong values override the checked identity yields different commit metadata and fails that assertion. fleet.py:1065,1071 shows the concrete environment-to-commit route. The current fixed fleet identity would also fail the planned fixture-identity assertion. The new test and corrected producer have not run. |
| Route skipping snapshot_identity | The current fleet source has one commit-tree producer, make_snapshot at :1071, and cmd_run calls it without an identity argument at :1091. The plan retains that default checked path for run and agent start (plan:591-594; :412). Member collect intentionally supplies the saved base identity instead: it has no member-global identity to compare, and must check the base suffix and every intervening author/committer before creating its snapshot (plan:600-605; AC-34). result separately compares to <hub host>'s checked identity before creating the result ref (plan:607-610; AC-35). No other planned production caller is authorized to inject an arbitrary identity. This is a trusted internal argument, not a guarantee against arbitrary code running as the same user. |
| Job-created commits | A job can itself run Git without calling snapshot_identity. The existing MVP test deliberately does so through Python at test_fleet_run.py:712-717,749-759; its result stays in the run slot. Plan:650 explicitly preserves that test, while plan:429 tells agent jobs to leave changes uncommitted, and AC-34/35 refuse collection/landing of intervening mismatched commits. The plan controls its snapshot producer and result acceptance; it does not sandbox every possible Git invocation. This existing limit does not justify adding an identity service or new enforcement layer. |
| Ruled scope and simplicity | D-1 to D-6 remain reflected in plan:297-347,408-460,511-545,655-661 and :803-868. P-1 remains member-only at :237-241,1024,1046-1048; P-2 is :1035,1050-1052. Codex messaging remains between turns, full execution sessions/project hooks remain outside the bounded-job scope, and Mat's words still gate starts/resumes/results. The corrections add an assertion update, a correctly scoped fixture and reuse of the existing env overlay. They neither widen deployment nor silently narrow the accepted A1-A6 work. |
| Prior correction dependencies | A-13 still fits the real wrapper path checks at Invoke-ClaudeDispatch.ps1:698-708 and Invoke-CodexDispatch.ps1:965-995. P-1's non-review worker avoids the real review-class resume refusal at CodexDispatch:595-600. A-15 still matches the copied per-run receipt at Register-CreditsRun.ps1:355-360 and the live version/revision checks at run_gate.py:227-236. These are source observations, not fresh runtime probes. |

### Checklist Results

All pass results below concern observed static plan readiness. No implementation or live acceptance is claimed.

| Check | Result | Procedure or command | Exit | Evidence |
|---|---|---|---|---|
| PR-1 alignment; PR-2 unstarted; PR-3 task contract | pass | Read plan/task; inspect explicit output paths; run lint_task_contract.py --task docs/execution/plans/2026-11-04-fleet-agents/task.md | 0 for linter; other observations manual, gpt-6.1-sol | 41 distinct ACs covering 1..41; all 44 task rows unchecked; no project implementation handoff/review; linter reports 44 rows and acyclic resolved dependencies. |
| PR-4 validation; PR-8 control reachability | pass | Manually trace the corrected snapshot and wrapper paths and compare negative observables with AC-34/35/40/41; observer gpt-6.1-sol | n/a, manual | Produced commit metadata, commit count, refs and sent blobs are concrete observables; changed source and tests are explicitly scheduled. Row 0 creates the three plan-local checkers. |
| PR-5 source basis; PR-7 scope | pass | Compare outline work order/D-1..D-6, supplied human rulings and plan Decision Log/Out of Scope; observer gpt-6.1-sol | n/a, manual | Member-only P-1 and global-config P-2 retained; bounded-job, hook and trust limits disclosed; no substantive scope drift found. |
| PR-6 census; DR-1/5/7 corrections evidence | pass | Independently parse raw receipts, compare all dispositions/current payloads/fresh pattern sites and target hashes; observer gpt-6.1-sol | n/a, manual | 9 before sites mapped; 10 after sites equal current search; hashes above match. |
| PR-9 definitions; DR-2/3/4/6/8 consistency | pass | Compare resolver/refusals/order/assertion clauses across plan/task and cited live dependencies; observer gpt-6.1-sol | n/a, manual | No materially conflicting operative identity or ordering clause found; earlier runtime claims have not been promoted into implementation completion. |
| Actual fixture setup/teardown, new AC tests and live behavior | n/a | Not run: unstarted plan | n/a | The new fixture, resolver and test_fleet_agent.py do not exist yet. Row 7a and the combined targeted/full gates must demonstrate isolation and environment-binding behavior; human rows must establish live S4U/auth/messaging/resume/results. No hub or <member host> contact occurred. |

~~~json
{"schema_version":"evidence.v1","check_id":"R4-resubmission-task-contract","command":"rtk proxy pwsh -NoProfile -Command 'rtk proxy python core/tools/lint_task_contract.py --task docs/execution/plans/2026-11-04-fleet-agents/task.md *> C:/Temp/agentic-framework/receipts/fa-review-r4-task-lint.txt; $reviewExit=$LASTEXITCODE; Get-Content C:/Temp/agentic-framework/receipts/fa-review-r4-task-lint.txt; exit $reviewExit'","cwd":"P:/agentic-framework","scope":"unstarted task contract","phase":"static","exit_code":0,"result":"pass","output":"OK: 44 row(s); 10-column table (with builder_model); 42 row(s) fully checked: backticked, exit-code re-raised, receipt under RECEIPTS_DIR; dependencies resolve and are acyclic; 2 row(s) exempt (view_file): H1-5, H2-1"}
~~~

~~~json
{"schema_version":"evidence.v1","check_id":"R4-resubmission-independent-audit","command":null,"procedure":"Read the round-4 correction map against both complete census receipts and every current matching line; inspect hashes and compare fresh pattern sites. Independently read the cited fixture/helper/member lifetime, snapshot producer/caller/env, P-2 resolver contract, member base/history checks, result checks and row order. Compare the full plan and task with the outline and cited live credits/wrapper/package contracts. Inspect the static inventory: 41 unique ACs, 44 unchecked rows, absent implementation handoffs and scheduled new paths.","observer":"gpt-6.1-sol","cwd":"P:/agentic-framework","scope":"F-005, F-010, F-011, fixture lifetime, identity environment, ruled scope and readiness","phase":"manual","exit_code":null,"result":"pass","output":"Before census 22 lines/13 hits/9 sites; after 29 lines/20 hits/10 sites; all old sites dispositioned, no current payload/site mismatch, both target hashes match the correction log. F-005 and F-010 still hold under P-2 and row 7a; F-011 and both new corrections hold as plan contracts. No supported remaining blocker. New implementation/runtime behavior remains unexecuted."}
~~~

### Verdict

**approved** — intent achieved **yes** for this unstarted plan. F-005, F-010 and F-011 are closed for plan review. The stated trust and runtime limits remain; no further correction is required before the existing human execution gate. Approval is not authorization to execute (plan:75-83; task:15-17,102).

The rolling handoff is .agent/context/handoffs/2026-11-04-fleet-agents-plan-critical-review.md. Only this handoff was edited; no plan, product, tool or test was changed, no commit was created, and no ledger record was manually submitted. The wrapper must validate and record the accompanying v2 JSON.

🕐 Completed: 2026-11-04 22:19 (EST)

