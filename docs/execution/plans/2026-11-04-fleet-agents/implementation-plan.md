---
project: "2026-11-04-fleet-agents"
date: "2026-11-04"
source: "docs/proposals/2026-11-04-fleet-agents-outline.md"
meus: []
run_parameters: "absent — run parameters are disabled in this repo (run_parameters.py status: policy_missing); Step 0 resolved manual"
status: "complete"
template_version: "2.4"
---

# Implementation Plan: Fleet Agents

> **Project**: `2026-11-04-fleet-agents`
> **Build Plan Section(s)**: none. This framework package has no `docs/BUILD_PLAN.md` hub. The scope source is outline §3, work order A1 to A6.
> **Status**: `in_progress`

---

## Goal

SUPER should be able to start a Claude or Codex job on another machine, talk to it while it runs, get
its question back, resume it with Mat's answer, and land its result, with no sign-in on that machine.

The fleet MVP already moves code and runs named commands. The credits engine already runs Claude
with mid-run messages, stop classes, budget caps and resume, and `Invoke-CodexDispatch.ps1` already
runs Codex. This plan connects them and builds no second runner. SUPER sends short `agent` tasks through
the hub. The member starts a detached scheduled task and answers at once, so it keeps polling. Later
short tasks call scripts that already exist.

It is done when, from SUPER, a Claude run on DUPER answers a mid-run `query`, stops on a question,
finishes after a resume on Mat's words, the same job finishes on Codex, a remote Claude run gets a Codex
answer, and one result from each CLI lands on SUPER on Mat's word.

## Context Tool Decision

```yaml
context_tool_decision:
  phase: planning_and_execution
  eligible_tools: []
  decision: not_applicable
  eligibility_basis: "graphify-out/graph.json is absent. Headroom 0.24.0 is installed, but the payloads here are source code and exact evidence, which are bypass classes in core/.agent/docs/context-tool-decision-gate.md."
  human_message_reference: null
```

## Handoff Set

`meus: []`, so there is one project handoff and one rolling review.

| Scope | Canonical path |
|---|---|
| Project handoff | `.agent/context/handoffs/2026-11-04-fleet-agents-handoff.md` |
| Plan review | `.agent/context/handoffs/2026-11-04-fleet-agents-plan-critical-review.md` |
| Rolling execution review | `.agent/context/handoffs/2026-11-04-fleet-agents-implementation-critical-review.md` |

## Work Packages and Context Lifecycle

| ID | Work | depends_on | context_strategy | durable_outputs |
|---|---|---|---|---|
| WP-A1 | Scripted member setup, with a real write test of each CLI | — | `shared` | `.agent/fleet/setup-member.ps1`; `scripts/tests/SetupMember.Tests.ps1`; live receipt |
| WP-A2 | Credits on a member: subscription auth, S4U, gate per member, home install | WP-A1 | `compact_continue` | `core/.agent/skills/claude-credits/*`; `.agent/fleet/member_kit.py`; `core/tools/tests/CreditsFleetMember.Tests.ps1`; live receipt. After compaction, re-read `task.md` and these outputs |
| WP-A3 | The `agent` task kind and `fleet watch` | WP-A2 | `compact_continue` | `.agent/fleet/fleet.py`; `scripts/tests/test_fleet_agent.py`; live receipt. After compaction, re-read `task.md` and these outputs |
| WP-A4 | Codex jobs, one at a time per member, and remote Claude calling Codex | WP-A3 | `compact_continue` | `.agent/fleet/fleet-tasks.ps1`; `core/tools/Invoke-CodexDispatch.ps1`; `core/tools/tests/CodexDispatchFleetLock.Tests.ps1`; live receipt. After compaction, re-read `task.md` and these outputs |
| WP-A5 | Results: collect, fetch to a non-branch ref on SUPER, drop. Row 7a builds its snapshot identity half first, before WP-A2's live row 8 | WP-A4 | `compact_continue` | `.agent/fleet/fleet.py`; `scripts/tests/test_fleet_agent.py`; live receipt. After compaction, re-read `task.md` and these outputs |
| WP-A6 | Rules and docs, then the package gates | WP-A5 | `shared` | `.agent/fleet/bootstrap.md`; both skill files; `core/MANIFEST.md`; gate receipt |

**Lane ownership: omitted.** This is a main-tree plan. The package repo is not instantiated: it has
no `.agent/credits/worktree.json`, so `executor_worktree.py` has no lane configuration here, and the
precedent plan `docs/execution/plans/2026-11-03-fleet-mvp/` ran on the main tree.

---

## User Review Required

> [!IMPORTANT]
> **Run parameters:** `manual`. They are disabled in this repo (`policy_missing`). Execution starts only
> when Mat says proceed after the plan is approved. Every commit needs Mat's word, and nothing is pushed.
>
> **Review limits:** `repo` (no `review_limits` block). Plan loop 3 rounds and 10,500,000 tokens,
> execution loop 6 rounds and 21,000,000 tokens, from `core/.agent/review-limits.json`.
>
> **Rows that change DUPER run when Mat asks.** They are rows 3, 8, 12, 15 and 17. Mat can name them all
> in one message when saying proceed. Live starts and resumes use Mat's own words as the quote, so rows 12,
> 15 and 17 need those words. Row 8 also needs Mat to read the plan usage meter and the Console balance.
>
> **Eight things planning found that the rulings did not cover. Each is reversible, and each can be
> overruled here:**
>
> 1. **The M-1 receipt gets looser, on the member route only (A-2).** Today a receipt is bound to one
>    project path. A slot per run would need a gate per run, so `--check-receipt` gains an optional
>    `--gate-project`. The CLI version, the user-level hooks and the kit revision are still compared, and
>    the slot's own hook digests must equal the gate project's. The key route passes no new argument and
>    behaves as it does today.
> 2. **A project that carries its own `.claude/settings.json` hooks is refused on a member (A-3).** That
>    includes av-kit and every instantiated project, and a settings file with no hooks in it, whose digest
>    differs from a missing file's. The receipt check fails closed until a gate for that
>    hook set exists. I'm deferring it because D-4 says "bounded jobs first". Live tests use a throwaway
>    repo with no hooks.
> 3. **`Status: DONE` from a bounded job records `done_unverified` in credits (A-4).** There is no plan,
>    capture or seal on a member. The fleet reports `done` with `verified: false`, and the evidence is the
>    result bundle. A `done_unverified` run can't be resumed, so a follow-up is a new run.
> 4. **`elevated` has no setup command (A-8).** `codex sandbox --help` shows only `uninstall`. A1's one
>    try sets `windows.sandbox="elevated"` and runs one `codex exec` write test in the elevated WinRM
>    session, then tests again under S4U. **That creates machine-wide accounts and network rules on DUPER.**
>    If it fails, the script runs `codex sandbox uninstall`, falls back to `unelevated` and records it.
> 5. **One Claude run at a time per member (A-7).** Every member run uses lane `fleet`, so a second start
>    is refused with `lane_busy` until the first finishes. Codex is already limited to one job by D-5.
> 6. **`.agent/fleet.json` becomes tracked in this repo (A-1)**, so the kit travels by the existing hash-checked
>    `run` route. A snapshot also carries untracked files, so DUPER's slot will hold this repo's local plan
>    `scripts/`, `check_live.py` and proposals. They hold no credentials, and a snapshot is never pushed.
> 7. **Snapshot commits take their identity from git config, and the fixed `fleet.invalid` identity goes
>    away, in the MVP's `run` route too (P-2, A-14).** SUPER's repo must have the same `user.name` and
>    `user.email` as the machine's global git config, and the address must be a GitHub noreply address, or the
>    snapshot is refused before any commit exists. All 33 repos under `P:/` pass today. Anyone adopting this template
>    needs a global identity with a noreply address, or a change to that one constant. If the global config itself
>    were changed to another noreply address, the check would pass. A member uses the identity of the commit SUPER
>    sent it, and refuses to collect a job's commit made under another identity.
> 8. **A stopped Claude run can't resume across a Claude CLI or probe-kit change (A-15).** A run keeps the gate
>    receipt it registered with, so a CLI auto-update or a new probe kit ends its ability to resume, even after
>    `kit-gate` passes. `agent resume` refuses with `receipt_stale`, and the run's work can still be collected or
>    dropped. The follow-up is a new run. An update that changes neither doesn't affect it.
>
> **Ruled: the Codex class binding exists only on members (P-1).** A fleet Codex job needs a model class that can
> resume, and only review classes are bound to Codex today. `run_member_setup.py` adds `isolated_worker` on
> `codex-cli` to the copy of the registry it carries to a member. `P:/.agent/model-registry.json` is never written.
> Any change to that file makes the 9 projects with a compiled overlay refuse dispatch with `overlay_not_validated`
> until each re-syncs, and the re-sync changes a tracked file in 8 of those repos. The limit: after a model bump on
> SUPER, a member keeps the old slug until setup runs again.
>
> **Risks that stay after this plan, stated so they aren't assumed away:**
>
> - Anything running as the member user can read both login files, including a prompt-injected agent. The
>   scrub clears the environment, not the file (D-1). Under `unelevated`, assume a Codex run can read the
>   Claude token file.
> - `setup-token` may have no revoke route (D-1). `fleet_auth.py remove` only deletes files.
> - An orchestrator-supplied allowed tool such as `Bash(python:*)` still runs anything (AC-20 refuses shells
>   and agent CLIs by first word, and that is all it can do).
> - A Codex job can still run bare `codex exec` inside its sandbox, which the job lock doesn't see (AC-31).
> - The result snapshot's secret check reads paths, not file contents (AC-34). This is why a result lands
>   only on Mat's word, into a non-branch ref.
>
> **Existing tests this plan changes, by name:**
>
> - `scripts/tests/test_fleet_hub.py::test_ac08_agent_kind_is_not_enabled` is deleted, and AC-17 replaces it.
>   `kind_not_enabled` then has no producer in `fleet.py`, so it leaves `REFUSALS`. The separate
>   `kind_not_enabled` in `core/tools/credits_state.py` is a different refusal, and it stays.
> - `scripts/tests/test_fleet_bootstrap.py`: `template_problems` loses its `("pair", "run-pair")` pair and
>   `test_ac19_the_checker_sees_the_other_breaks` loses its `fleet.py pair` assertion, because `run-pair` is no
>   longer a human stop (D-6).
> - The `Interactive` pins at `Register-CreditsRun.Tests.ps1:256,268` and `CreditsTaskReadback.Tests.ps1:18,60`
>   are unchanged (D-2). The member route gets its own cases.
>
> **D-1 departs from a handoff rule, and Mat ruled on it.** "Logins and keys are created by a human at each
> member's console, never copied" gives way for Mat's own account on Mat's own machines only. "No secrets
> in a message or a brief" stands: credentials never go through the hub, and the hub log is permanent.

---

## Proposed Changes

### Named definitions

Every set and limit used by more than one AC is defined here, once, as a module-level constant in
`.agent/fleet/fleet.py`. ACs refer to these names. A test imports the constant, so it never restates the
values. Rows marked "changed" edit a constant that already exists.

| Name | Value |
|---|---|
| `SEND_POLICY` (changed) | `{orchestrator: {ping, run, agent}, member: {}}` |
| `EXECUTORS` (changed) | `ping, run, agent`. Still equals the union of the `SEND_POLICY` values |
| `CAPABILITY_TOOLS` (changed) | Adds `pwsh` |
| `BOOTSTRAP_STOPS` (changed) | `browser-approval, firewall-rule, run-approve` (D-6) |
| `EXIT_CODES` (changed) | Adds `stopped: 7`. The rest are unchanged |
| `REFUSALS` (changed) | Removes `kind_not_enabled`. Adds the codes below |
| `TRANSITIONS` | Unchanged. Each action is a short task with its own `task_id` |
| `FORBIDDEN_COMMANDS` | Unchanged. It governs `run` manifests, and an `agent` body has no command field (D-5) |
| `AGENT_ACTIONS` | `start, status, message, stop, resume, collect, drop` |
| `QUOTE_ACTIONS` | `start, resume`. These need a non-blank `start_quote`, and every other action must carry `null` |
| `AGENT_CLIS` | `claude, codex` |
| `AGENT_BODY_FIELDS` | Per action. `start`: `run, action, cli, brief`, plus optional `timeout_sec, model, effort`. Claude adds required `segment_cap_usd, run_cap_usd` and optional `allowed_tools, allow_codex`, and a Codex start refuses those four. `message`: `run, action, message_kind, text`. `resume`: `run, action, brief`. `status, stop, collect, drop`: `run, action`. A `start` carries `refs` of `RUN_REFS_FIELDS`; every other action carries empty `refs` |
| `AGENT_MESSAGE_KINDS` | `info, query, stop-after-row`. `ruling` is refused with `message_kind_refused`, because a live ruling checks a transcript that is on SUPER (outline §3) |
| `AGENT_SHELLS` | `cmd, powershell, pwsh, sh, bash, claude, codex, cswap` |
| `AGENT_RUN_STATES` | `running`: `registering, registered, requested, waiting, launching, running, finalizing`. `done`: `done`, and `done_unverified` with a final status of `DONE`, which sets `verified: false`. `stopped`: `stopped, parked, done_unverified` (otherwise), `failed, cancelled, registration_failed`. Any other value is `unknown`, which fails closed. A run with a segment whose `finalized_utc` is empty counts as `running`, whatever its state, because `cancel` moves a run to `cancelled` before its segment ends (`credits_state.py:2663-2679`) |
| `AGENT_FINAL_MAX_BYTES` | 64 KiB, the tail of `final.md` kept in a status body |
| `WATCH_POLL_S` | 60 |
| `CODEX_MODEL_CLASS` | `isolated_worker`. Passed as `-ModelClass` on every fleet Codex start and resume, because the wrapper refuses a resume on a review class (`Invoke-CodexDispatch.ps1:595-600`). Bound only in a member's registry copy (P-1) |
| `SNAPSHOT_EMAIL_SUFFIX` | `@users.noreply.github.com`. The only address form a snapshot may carry. It names no person |
| `snapshot_identity(repo)` | SUPER's identity check (P-2). Returns the repo's effective `user.name` and `user.email`. `identity_missing` if either is unset in the repo's effective config or in the global config. `identity_mismatch` if either differs from the global value, or the address doesn't end with `SNAPSHOT_EMAIL_SUFFIX` |
| `CODEX_BUSY_EXIT` | 11, in `Invoke-CodexDispatch.ps1`. The wrapper's exit codes 0, 1, 3 and 9 are taken |
| Member paths | Under `FLEET_HOME`: `kit/`, `kit-new/`, `gate-project/`, `receipts/`, `receipts/gate/gate-result.json`, `receipts/fleet-briefs/<run>/brief-<n>.md`, `credentials/claude-oauth-token`, `codex.lock`, `agent/<run>/` with `slot/`, `base`, `manifest.json`, `collected` |
| Task paths | `\Fleet\Credits\<run>` and `\Fleet\Credits\Monitor`, from the kit's `PROJECT_NAME=fleet`. `\Fleet\Codex\<run>`. A run's task is any of these except `\Fleet\Credits\Monitor` |

**New refusal codes:** all `422`: `quote_required`, `quote_not_allowed`, `unknown_action`,
`bad_agent_body:<reason>`, `message_kind_refused`. New CLI refusals, exit `2`: `result_exists`, `identity_missing`,
`identity_mismatch`.

**Task outcome reasons,** in `body.reason`: `run_exists`, `run_unknown`, `kit_missing`, `gate_missing`,
`token_missing`, `tool_missing:<n>`, `credits_refused:<step>:<exit>`, `codex_job_busy`, `codex_no_messages`,
`not_collected`, `run_active`, `receipt_stale`, `identity_missing`, `identity_mismatch`, `output_withheld`,
`snapshot_secret_risk:<path>`, `bundle_bad`, `tree_mismatch`.

**`member_kit.py` exit reasons,** printed on stderr with a non-zero exit: `run_active`, `kit_busy`, `token_missing`,
`gate_token_leak`.

**Member status body:** `{state: completed, run, cli, run_state, stop_class, final_status, verified,
final_text, outbox}`. `run_state` is a key of `AGENT_RUN_STATES` or `unknown`.

**Call chains.** Control ACs name one of these. `C-HTTP`, `C-CLI` and `C-MEMBER` are defined in the fleet
MVP plan and are unchanged.

| Chain | Path |
|---|---|
| `C-AGENT-HUB` | `fleet.py agent <action>` → `main` → `cmd_agent` → `hub_request` → `C-HTTP` → `route_post_task` → `validate_agent_task` → `Store` |
| `C-AGENT-MEMBER` | `C-MEMBER` with `EXECUTORS["agent"]` = `execute_agent` → `AGENT_HANDLERS[action]` → `member_script` (`pwsh -NoProfile -File <kit script>`) → `post_status` |
| `C-CREDITS` | `Register-CreditsRun.ps1` → `Assert-Receipt` → `run_gate.py --check-receipt`, then `New-CreditsTaskDefinition` → scheduler adapter. At launch: `Start-CreditsRun.ps1` → `Test-RunReceipt` → `Invoke-ClaudeCredits.ps1 -Scheduled` → `-LaunchHook` → `Invoke-ClaudeDispatch.ps1` → `claude` |
| `C-CODEX` | `fleet-tasks.ps1 -Action CodexRun` → `Invoke-CodexDispatch.ps1 -NonReviewDispatch` → the `FLEET_CODEX_LOCK` block → `codex exec` |
| `C-KIT` | `fleet.py run` → `C-MEMBER` with `execute_run` → `run_steps` → `python .agent/fleet/member_kit.py install\|gate` |

**Atomicity.**

- Hub checks run before `Store.tx()`, so a refused task adds no row.
- `member_kit.py install` builds `kit-new/` and verifies it, then renames `kit/` aside, renames `kit-new/` to
  `kit/` and deletes the old copy. A rename that fails on an open file restores the old `kit/` and exits `kit_busy`.
  A crash between the renames leaves no `kit/`, so starts fail closed with `kit_missing`, and a re-run recovers.
- `~/.claude/settings.json` is merged by writing a temporary file and `os.replace`.
- A run folder is created by renaming `agent/<run>.tmp`, so a partly built run never reads as existing.
- A result ref lands with `git update-ref refs/fleet/result/<run> <commit> 0{40}`, after the tree check, so an
  existing ref is never overwritten.
- The Codex lock is an exclusive file handle held for the wrapper's life, released when its process ends.

### WP-A1: Scripted member setup

`.agent/fleet/setup-member.ps1` (new, tracked, no hosts or credentials) runs on the member. The local helper
`docs/execution/plans/2026-11-04-fleet-agents/scripts/run_member_setup.py` (untracked) carries it over WinRM,
with a copy of `P:/.agent/model-registry.json`, and runs it in the elevated admin session. Nothing is read from
`P:/.agent/notify/`, and credentials stay in the local `fleet_auth.py`.

**Member registry (P-1).** The helper reads SUPER's registry and writes nothing back to it. In the copy it sets
`classes.isolated_worker.bindings["codex-cli"]` to `{slug: <slug>}`, with the slug taken from
`classes.independent_reviewer.bindings["codex-cli"]`, so no model name is written into the helper and a re-run follows
a bump on SUPER. It stops if that reviewer binding is missing. A member has no compiled overlay, so the copy's
different hash refuses nothing. `setup-report.json` records the copy's `isolated_worker` slug on `codex-cli`.

Each step tests and then acts: install `claude`, `codex`, `pwsh` and `uv` if missing, from the URLs already
used by the local `duper-agents.ps1` and `duper-tools.ps1`; set Codex's `cli_auth_credentials_store="file"` and
`windows.sandbox`; run a real write test of each CLI under a one-shot S4U task; write
`setup-report.json` with `changed`, the versions, `sandbox`, `elevated_tried` and each write test's result. It
never reads `auth.json` or a token's value into its own output, and it never parses `auth.json`
(`cli-dispatch/SKILL.md:47`). The Claude write test passes the token through the child's environment and
sets a budget cap.

**Sandbox selection (`Select-CodexSandbox`, D-4, A-8).** A write test passes only if the expected file exists
with the expected contents, whatever the exit code. If `elevated_tried` is false: set `elevated`, run the
admin-session `codex exec` once, test under S4U, and keep it if that passes. If it doesn't, run `codex sandbox
uninstall`, set `unelevated` and test again. The report's `elevated_tried: true` stops a re-run from trying again.

**Amended by P-4 (2026-11-05).** The chosen sandbox's result is recorded as `write_tests.codex_sandbox` and no longer
fails setup, because only a Claude job's Codex call uses it. `write_tests.codex` is a write under `danger-full-access`,
the way a Codex job runs, and its failure exits `1` with `codex_no_write`.

#### Boundary Inventory

| Surface | Schema Owner | Field Constraints | Extra-Field Policy |
|---------|-------------|-------------------|-------------------|
| `setup-member.ps1` parameters | PowerShell `param` block | `-LibraryOnly` switch only; everything else is derived from the machine | PowerShell binding error |
| `setup-report.json` | Written only by `setup-member.ps1` | Fields above; read by `check_live.py setup` | Unknown fields fail the live check |
| Codex `config.toml` | Codex CLI | Two keys set by exact line; other lines stay byte-identical | Not parsed beyond those keys |

#### Acceptance Criteria

| AC | Type | Description | Source | Negative Test |
|----|------|-------------|--------|---------------|
| AC-1 | unit | Source rules, by AST and text. The MVP's AC-4 checker also covers `.agent/fleet/member_kit.py`: stdlib imports only, parses at `feature_version=(3, 11)`, no drive-letter path, no `CLAUDE_CODE_ENTRYPOINT`, `CLAUDECODE` or `cswap`. `CAPABILITY_TOOLS` holds `pwsh`, and a member's `hello` reports it. | Human-approved (handoff billing rule, `SKILL.md:340-343`) | A copy of the source with `import requests` fails the same checker, and so does one naming `CLAUDECODE` |
| AC-2 | unit | `setup-member.ps1` publishes no host or credential (D-6). Observable: the checker's problem list. | Human-approved (D-6, plan D-13) | Copies with an IPv4 literal, `DUPER`, `SUPER`, a drive-letter path, `setup-token`, or a read of `auth.json` or `.credentials.json` each fail. The clean file passes |
| AC-3 | integration | Setup is idempotent. Chain: `setup-member.ps1` → `Install-MemberTool` and `Set-CodexConfigLine`, with `Invoke-Installer` mocked. Observable: mock call counts, `changed`, and `config.toml` bytes. Installs only what's missing. | Human-approved (outline §3 A1) | With every tool present, `Invoke-Installer` is called zero times, `changed` is empty and `config.toml` bytes don't change. With `codex` absent, exactly one call. A `config.toml` with other lines keeps them byte-identical |
| AC-4 | integration | The sandbox is chosen by a real write, never by exit code. Chain: `Select-CodexSandbox` → `Test-CodexWrite` (S4U run mocked; file check real). Observable: chosen sandbox, `elevated_tried`, mock calls. | Human-approved (D-4); Research-backed (openai/codex 34961) | Exit 0 with no file is a fail. Elevated fail then unelevated pass chooses `unelevated` and calls `codex sandbox uninstall` once. Both fail: recorded as `codex_sandbox: fail`, and the run exits `0` if the full-access write passes; a failed full-access write exits `1` with `codex_no_write` (P-4 replaced "both fail: exit `1` with `sandbox_no_write`"). `elevated_tried: true` makes no elevated attempt |
| AC-5 | integration | **Live, human row 3.** On DUPER, `setup-member.ps1` runs twice. Observable: `check_live.py setup` reads both reports and `fleet status`: the second has empty `changed`, both write tests pass under S4U, the sandbox and elevated outcome are recorded, the report's `isolated_worker` slug on `codex-cli` equals SUPER's `independent_reviewer` slug there, SUPER's registry hash is unchanged, and `fleet status` reports `claude`, `codex` and `pwsh` with versions. | Human-approved (outline §3 A1 done-when, P-1) | `check_live.py --selftest` feeds a report with a non-empty `changed`, one with a failed write test, one with no `isolated_worker` slug, and a changed SUPER registry hash, and each must fail |

#### Spec Sufficiency Table

| Behavior | Classification | Resolution |
|----------|---------------|------------|
| What setup installs and what's published | Human-approved | Outline §3 A1, D-6 |
| Sandbox selection | Human-approved | D-4 |
| How `elevated` gets its setup | Research-backed | A-8: `codex sandbox --help` and the Codex Windows doc name no setup command |
| Install URLs | Local Canon | The local `duper-agents.ps1` and `duper-tools.ps1` that ran on DUPER |

#### Files Modified

| File | Action | Summary |
|------|--------|---------|
| `.agent/fleet/setup-member.ps1` | new | Setup script |
| `.agent/fleet/fleet.py` | modify | `pwsh` in `CAPABILITY_TOOLS` |
| `scripts/tests/SetupMember.Tests.ps1` | new | AC-2 to AC-4 |
| `scripts/tests/test_fleet_agent.py` | new | AC-1 |
| `docs/execution/plans/2026-11-04-fleet-agents/check_live.py` | new, untracked | Live checks and `--selftest` |
| `docs/execution/plans/2026-11-04-fleet-agents/scripts/` | new, untracked | WinRM helper and live scripts (plan D-13, D-15) |

### WP-A2: Credits on a member

**The route.** `launch.auth: subscription` is new and the key route stays the default, so SUPER is unchanged.

- **Schema:** `launch` gains `auth` (`key` default, `subscription`), `allowed_tools` (string array) and
  `gate_project` (string). `Register-CreditsRun.ps1` refuses `gate_project` without `auth: subscription`,
  with `manifest_invalid`.
- **Task definition:** with `auth: subscription`, `New-CreditsTaskDefinition` and
  `New-CreditsMonitorTaskDefinition` use `LogonType='S4U'`, and the monitor drops `AtLogOn` and keeps its
  five-minute repeat, since nobody logs on. `New-CreditsSchedulerAdapter:982` already passes the logon type through.
- **No key:** Register and Start skip the key-file checks for this route. Start passes `-Subscription
  -TokenFile <path>` to `Invoke-ClaudeCredits.ps1` in place of `-KeyFile`.
- **The token:** with `-Subscription`, Invoke skips the key checks and `ApiKeyFile`, and its `-Scheduled`
  `-LaunchHook` also reads the token file, sets `CLAUDE_CODE_OAUTH_TOKEN` and
  `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1`, and removes `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` from the
  child's `StartInfo`. It never prints the token and never touches `CLAUDECODE` or `CLAUDE_CODE_ENTRYPOINT`.
- **Allowed tools:** Start passes `launch.allowed_tools` as `-AllowedTools` (it doesn't pass any today, per
  `Start-CreditsRun.ps1:590-602`). `permission_mode` is `acceptEdits` on this route (D-4).
- **Resume:** `Start-CreditsRun.ps1:574-575` resumes with `-Resume <source>`, so a resumed launch takes the same
  `-Subscription` path and hook. The fleet never calls `-Continue`, so its key-file filter stays as it is.

**The M-1 gate (A-2).** `check_receipt(path, project, claude, python, gate_project=None)` compares
`ident.project` with `gate_project or project`. `check_profile` still uses the slot. `Assert-Receipt` and
`Test-RunReceipt` pass `--gate-project` only when `launch.gate_project` is set. The gate runs once per member in
the fixed, empty `gate-project/`, after the user-level hooks are in. A CLI update blocks new runs until the gate
runs again: a gate step, not a waiver (D-2).

**One install (A-1).** A tracked `.agent/fleet.json` names `kit-install` and `kit-gate`. SUPER runs `fleet.py
publish` and `fleet.py run duper kit-install`, so the kit moves by bundle with no WinRM copy and no new route.
`.agent/fleet/member_kit.py` (new, stdlib):

- `install` refuses with `run_active` if a run's task is `Running`, read through `pwsh Get-ScheduledTask`. Stopped
  and finished run folders stay: they live outside `kit/`, and a new kit has the same path. Otherwise it copies the
  slot's `core/` to `kit-new/`, runs `scripts/instantiate.py --root kit-new --config <vars>` with `PROJECT_NAME=fleet`,
  `PROJECT_ROOT=<FLEET_HOME>`, `RECEIPTS_DIR=<FLEET_HOME>/receipts`, a local placeholder `REPO_URL` and
  `CREDITS_START_POLICY=agent-on-user-chat` (D-3), then `--verify`, and swaps. `PROJECT_ROOT` is `FLEET_HOME`, not
  the kit, so the Codex wrapper accepts a slot as its working directory, and briefs live under `receipts/`, which both
  wrappers accept (A-13). A new kit revision needs `kit-gate` again before the next start. A retained stopped run keeps the receipt it
  registered with, so it can't resume across a probe-kit or CLI change (A-15). It copies `.agent/fleet/fleet-tasks.ps1`
  into `kit/fleet/`, copies `.agent/tools/ModelRegistry.psm1` to `~/.agent/tools/` (where
  `Invoke-ClaudeDispatch.ps1:612-620` looks), writes `FLEET_CODEX_LOCK` to the credits launcher env file, and merges
  the user-level hooks.
- **User-level hooks (A-5):** `~/.claude/settings.json` (or `CLAUDE_CONFIG_DIR`) gains `PostToolUse *` and `Stop`
  entries with absolute kit paths to `credits_inbox.py` only. The merge is additive and repeatable. `stop_gate` and
  `commit_gate` stay out: a slot has no real plan, and a member has no route to commit.
- `gate` reads the token file, never prints it, and runs
  `kit/.agent/skills/claude-credits/probes/run_gate.py --project gate-project --python --claude` in the scheduled
  route's child environment: `CLAUDE_CODE_OAUTH_TOKEN` and `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` set, and
  `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` removed. The receipt goes to `receipts/gate/gate-result.json`. Probes
  keep the CLI's text in that file, so when the child ends `gate` scans every file under `receipts/gate/` and
  `gate-project/` for the token's bytes. On a hit it deletes those files, so no usable receipt is left, and exits
  `gate_token_leak`. It also replaces the token in the child's output with `[redacted]` before printing, because the
  log goes to the hub as a blob.

#### Boundary Inventory

| Surface | Schema Owner | Field Constraints | Extra-Field Policy |
|---------|-------------|-------------------|-------------------|
| Credits manifest `launch` | `schemas/credits-run.v1.json` and `Register-CreditsRun.ps1` | `auth` enum; `allowed_tools` matches the wrapper's regex at `Invoke-ClaudeDispatch.ps1:796-802`; `gate_project` a local path, only with `subscription` | `additionalProperties: false` |
| `run_gate.py --check-receipt` argv | `argparse` in `run_gate.py` | `--gate-project` is an optional path | `argparse` rejects unknown flags |
| `.agent/fleet.json` | `validate_manifest` | `v, project, requires, commands`; `python` first word, not in `FORBIDDEN_COMMANDS` | `unknown_field:<n>` |
| `member_kit.py` argv | `argparse` | `install` or `gate` | `argparse` rejects |
| Token file | Written by the local `fleet_auth.py` | Read only by `member_kit.py gate` and Invoke's hook; empty refused | Never parsed, printed or sent |
| `~/.claude/settings.json` | Claude Code | Additive merge under `hooks`; other keys byte-equal after a JSON round trip | Preserved |

#### Acceptance Criteria

| AC | Type | Description | Source | Negative Test |
|----|------|-------------|--------|---------------|
| AC-6 | integration | Manifest rules. Chain: `Register-CreditsRun.ps1` → schema check. Observable: exit code and refusal code. A manifest with `auth` absent behaves as `key`. | Human-approved (D-2) | `auth: "x"` refused. `gate_project` with `auth: key` → `manifest_invalid`. Unknown `launch` key refused |
| AC-7 | integration | Logon by route. Chain: `C-CREDITS` with the injected scheduler adapter. Observable: `def.LogonType`, the monitor's triggers, and the readback hash. | Human-approved (D-2) | `auth: subscription` gives `S4U` and no `AtLogOn`. The key route still gives `Interactive` with `AtLogOn`, by the same assertions as the existing pins |
| AC-8 | integration | No key on the member route, and no change on the key route. Chain: `C-CREDITS`. Observable: exit code and argv recorded by a stub. | Human-approved (D-2) | `auth: subscription` with no key file registers and launches, and argv has no `-KeyFile`. `auth: key` with no key file still gives `key_missing` |
| AC-9 | integration | The token reaches `claude` and nothing else. Chain: `C-CREDITS` to a stub `claude`, which records env **names** and a hash of the token's value. Observable: that record, plus wrapper stdout, stderr and every file in the run folder. | Human-approved (D-1) | Present: `CLAUDE_CODE_OAUTH_TOKEN` and `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1`. Absent: `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, with both set in the parent. The value appears in no output or file. A missing or empty token file refuses with `token_missing` and the stub never starts. A source check finds no assignment to `CLAUDECODE` or `CLAUDE_CODE_ENTRYPOINT` in the new code |
| AC-10 | integration | `launch.allowed_tools` and `acceptEdits` reach the CLI. Chain: `C-CREDITS` to a stub `claude`. Observable: its argv. | Human-approved (D-4) | With `allowed_tools` absent, no `--allowedTools` flag. A key-route manifest's argv equals today's |
| AC-11 | unit | `check_receipt` with `gate_project`. Observable: its verdict. The slot differs from the gate project, and the identity binds to the latter. | Human-approved (D-2); Local Canon (A-2) | Rejected: a different CLI version, changed user-level hook settings, a slot with a `.claude/settings.json` hook, a slot with a hook-free settings file, a wrong gate project, and any receipt whose project isn't the slot when `gate_project` is absent |
| AC-12 | integration | Plumbing. Chain: `Assert-Receipt` and `Test-RunReceipt` → the mock gate, which records its argv. | Local Canon (A-2) | `--gate-project` appears only when `launch.gate_project` is set. A key-route manifest's argv equals today's |
| AC-13 | integration | Resume on this route. Chain: `Start-CreditsRun.ps1` → `Invoke-ClaudeCredits.ps1 -Subscription -Resume <source>` → `-LaunchHook` → stub `claude`. Observable: the stub's argv and env names. A resumed launch gets the token and the scrub. | Human-approved (D-1, D-3) | With no key file it still launches on this route. Without `-Subscription`, a missing key file still stops with `key file not found` |
| AC-14 | integration | `member_kit.py install`. Chain: `C-KIT` from `main`, with `FLEET_HOME` and `CLAUDE_CONFIG_DIR` in a temp folder. Observable: the kit's files, `config.json`, `settings.json` and exit code. No placeholder remains, the filled project root is `FLEET_HOME`, the policy is `agent-on-user-chat`, the task path is `\Fleet\Credits\`, and the merge keeps other keys. | Human-approved (D-3, outline §3 A2) | A run's task `Running`, by a `pwsh` shim, gives `run_active` and leaves `kit/` byte-identical. `\Fleet\Credits\Monitor` running doesn't block. A retained stopped run folder doesn't block: the install succeeds and the folder is intact. A failing `--verify` leaves the old `kit/`. A rename failing on a held file restores the old `kit/` and gives `kit_busy`. A second install adds no duplicate hook. The real `~/.claude/settings.json` is untouched, by its hash |
| AC-15 | integration | `member_kit.py gate`. Chain: `C-KIT` with a stub `run_gate.py` and a fake token. Observable: stub's env names, stdout, exit code, and every file under `receipts/gate/` and `gate-project/`. Present: `CLAUDE_CODE_OAUTH_TOKEN`, `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1`. Absent: `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, with both set in the parent. A clean stub leaves the receipt and exits 0. | Human-approved (D-1, D-2) | A missing or empty token file exits non-zero with `token_missing`. A stub that writes the fake token into `gate-result.json` exits non-zero with `gate_token_leak`, no receipt is left, and no persisted file holds the value. A stub that echoes the token has it redacted in the output |
| AC-16 | integration | **Live, human row 8.** On DUPER: install, gate, then a credits run started locally under S4U with the subscription token, finishing with `Status: DONE`, a hook firing under the scrub (an `info` message is acknowledged), and `--max-budget-usd` in the argv. P-3 replaces Mat's plan usage and Console readings with Mat's ruling and a stream test of the token. Observable: `check_live.py credits`. | Human-approved (D-2, outline §3 A2 done-when) | `--selftest` feeds a view with no acknowledged message, and one with `auth_mode: api_key_file`, and each must fail. If Mat sees a Console charge, stop condition 3 applies |

#### Spec Sufficiency Table

| Behavior | Classification | Resolution |
|----------|---------------|------------|
| Engine, auth and S4U | Human-approved | D-2 |
| Token path and scrub | Human-approved | D-1 |
| Start policy | Human-approved | D-3 |
| Receipt bound to a gate project | Local Canon | A-2: `run_gate.py:232`, `Assert-Receipt` at `Register-CreditsRun.ps1:261`, `Test-RunReceipt` at `Start-CreditsRun.ps1:209` |
| Filled project root and brief location | Local Canon | A-13: `Invoke-CodexDispatch.ps1:965-969,991-995`, `Invoke-ClaudeDispatch.ps1:698-708` |
| Kit update with retained runs | Local Canon | A-15 |
| Kit moved by `run` | Local Canon | A-1: AC-22 to AC-30 of the MVP plan |
| Which hooks go at user level | Local Canon | A-5 |

#### Files Modified

| File | Action | Summary |
|------|--------|---------|
| `core/.agent/skills/claude-credits/schemas/credits-run.v1.json` | modify | `launch.auth`, `allowed_tools`, `gate_project` |
| `core/.agent/skills/claude-credits/Register-CreditsRun.ps1` | modify | Cross-field rule, key check by route, `--gate-project` |
| `core/.agent/skills/claude-credits/Start-CreditsRun.ps1` | modify | Token route, `-AllowedTools`, `--gate-project` |
| `core/.agent/skills/claude-credits/Invoke-ClaudeCredits.ps1` | modify | `-Subscription -TokenFile`, hook |
| `core/.agent/skills/claude-credits/CreditsRun.psm1` | modify | S4U on both task definitions |
| `core/.agent/skills/claude-credits/probes/run_gate.py` | modify | `--gate-project` |
| `core/tools/tests/CreditsFleetMember.Tests.ps1` | new | AC-6 to AC-10, AC-12, AC-13, AC-22, AC-23 |
| `core/tools/tests/test_credits_fleet_gate.py` | new | AC-11 |
| `scripts/instantiate.py` | modify | Both new test files join `WINDOWS_ONLY_FILES` |
| `.agent/fleet/member_kit.py` | new | `install`, `gate` |
| `.agent/fleet.json` | new | `kit-install`, `kit-gate` |
| `scripts/tests/test_fleet_agent.py` | modify | AC-14, AC-15 |

### WP-A3: The `agent` task kind and `fleet watch`

**Verbs on SUPER (`C-AGENT-HUB`).** `fleet.py agent start <member> <run> --repo R --brief F --quote Q [--cli
claude|codex] [--allowed-tool X ...] [--allow-codex] --segment-cap-usd N --run-cap-usd N [--timeout-sec N]
[--model M] [--effort E]`; `agent status|stop|collect|drop <member> <run>`; `agent message <member> <run> --kind K
--text T`; `agent resume <member> <run> --brief F --quote Q`. Each sends one task and waits for its status.
`start` makes a snapshot with `make_snapshot` and uploads it as `run` does.

**Hub check.** `route_post_task` calls `validate_agent_task` for `kind: agent`: closed fields per action, the
quote rule, `agent_tool_refused` on each `allowed_tools` entry, and `missing_blob`. `agent_tool_refused(entry)` is
true for bare `Bash`, `Bash(*)`, `Bash(:*)`, a rule whose first word is in `AGENT_SHELLS`, and any entry containing
`codex`. D-5 access comes only through `allow_codex`. Hub also inserts `task_blobs` for a `start`.

**Member start, Claude (`C-AGENT-MEMBER`).** The handler refuses with a reason, in order: `run_exists`,
`tool_missing:pwsh`, `kit_missing`, `gate_missing`, `token_missing` (existence only: `fleet.py` never opens the
token file). Then:

1. `fetch_snapshot`, shared with `prepare_slot`, puts the bundle into `agent/<run>/slot`, a `git init` with no remote.
   The commit it received is written to `agent/<run>/base`, outside the slot.
2. Add `.fleet-run/` to the slot's `.git/info/exclude`, so a snapshot's `git add -A` skips it.
3. Write `.fleet-run/task.md` with `stop_gate: "armed"` and one open row, and
   `receipts/fleet-briefs/<run>/brief-1.md`: a fleet header, then the orchestrator's brief. The header gives Mat's words, makes `python <kit>/tools/credits_msg.py authority --quote
   "<words>"` the first action, and says: on a question, write `stop_gate: "released:human-gate"` and end
   `Status: STOPPED:decision`; on finishing, end `Status: DONE`. It also says to leave changes uncommitted, because `collect` makes the commit. Paths
   use forward slashes, for Git Bash.
4. Write `manifest.json`: `project_root` and `working_directory` the slot, `plan_folder: ".fleet-run"`, `kind: exec`,
   `lane: fleet`, `depends_on: []`, `messaging: {orchestrator_sessions: [], ruling_enabled: false,
   gate_wait_max_min: 0}`, `permission_mode: acceptEdits`, `auth: subscription`, `gate_project`, the caps, and
   `claude_exe` and `python_exe` from `shutil.which`. `allowed_tools` always adds
   `Bash(python <kit>/tools/credits_msg.py:*)`.
5. `Register-CreditsRun.ps1 -Manifest -Receipt`, then `Start-CreditsRunTask.ps1 -RunId -StartedBy agent-on-user-chat
   -StartQuote <words> -AcceptTimeoutMs 30000 -OutcomeTimeoutMs 30000`. Exit 0 or 4 completes the task. Anything else
   rejects with `credits_refused:<step>:<exit>`.

**Later actions.** `status` runs `Get-CreditsRun.ps1 <run> -Export` and normalizes `view.json` by
`AGENT_RUN_STATES`: `class` becomes `stop_class`, and `final_text` comes from the latest segment's `final.md`, since the
export doesn't carry it. `message` runs `Send-CreditsRunMessage.ps1`. `stop` runs `Stop-CreditsRun.ps1`. `resume` of a Claude run
first runs `probes/run_gate.py --check-receipt <receipts>/credits/receipts/<run>.gate-result.json`, with the manifest's
`project_root`, `gate_project`, `python_exe` and `claude_exe`, the same arguments the launcher passes
(`Start-CreditsRun.ps1:209`). A failure refuses with `receipt_stale` and changes nothing. Otherwise it writes
`receipts/fleet-briefs/<run>/brief-<n>.md`, sets `stop_gate` back to `armed`, and runs `Start-CreditsRunTask.ps1 -Resume -Brief <path>
-ResumeMode session` with the new quote, in the same slot and session.

**Why the classifier needs `.fleet-run/task.md` (A-4).** `Get-RunClass` in `Watch-CreditsRuns.ps1` reads `task.md` at
`<project_root>/<plan_folder>`. `STOPPED:decision` without `stop_gate: "released:human-gate"` classifies as `unknown`.
With the generated file it classifies as `decision`. No classifier change is needed.

**Withheld output.** A status body carrying secret-shaped text gets `422 secret_in_message`, and today `member_call`
re-raises that and ends the member. `execute_task` now catches that code, drops `final_text` and `outbox`, and posts
again with `reason: output_withheld`.

**`fleet watch <member> <run>`.** Sends `status` every `WATCH_POLL_S`, prints one JSON line when `run_state` isn't
`running`, and exits: `0` done, `7` stopped, `1` unknown, `3` rejected, `5` member offline. The orchestrator runs it
in a background shell, whose exit wakes the orchestrator. The orchestrator asks Mat, and Mat's words start the
resume. Nothing in the fleet answers a question by itself (D-3).

#### Boundary Inventory

| Surface | Schema Owner | Field Constraints | Extra-Field Policy |
|---------|-------------|-------------------|-------------------|
| `POST /v1/tasks`, `kind: agent` | `validate_agent_task` after `validate_envelope` | `AGENT_BODY_FIELDS` per action; `run` matches `NAME_RE`; `action` in `AGENT_ACTIONS`; `cli` in `AGENT_CLIS`; `message_kind` in `AGENT_MESSAGE_KINDS`; caps positive numbers; `timeout_sec` positive integer; `effort` from the credits schema enum; `refs` per the table; `start_quote` per `QUOTE_ACTIONS`; `allowed_tools` not refused by `agent_tool_refused` | Refuse: `bad_agent_body:unknown_field:<n>` |
| `POST /v1/tasks/<id>/status`, agent | `route_post_status` and `validate_envelope` | Member status body; secret check | Free fields, as in the MVP, under `MAX_JSON_BYTES` |
| `view.json` from `Get-CreditsRun.ps1 -Export` | `credits_state` | Read fields pinned by AC-23 | Other fields ignored |
| `fleet.py agent\|watch` argv | `argparse` | `member` and `run` match `NAME_RE` | `argparse` rejects |
| `.fleet-run/task.md` | Written by the member; edited by the run | `stop_gate` read by `Read-TaskState` | Excluded from snapshots |

#### Acceptance Criteria

| AC | Type | Description | Source | Negative Test |
|----|------|-------------|--------|---------------|
| AC-17 | integration | Who may send `agent`. Chain: `C-AGENT-HUB`. Observable: HTTP code and `messages` row count. `EXECUTORS` equals the union of `SEND_POLICY`. `kind_not_enabled` is gone from `REFUSALS` and `fleet.py`. | Human-approved (D-3) | A member sending `agent` → `403 sender_not_allowed`, zero rows. Landing kinds still → `422 unknown_kind`, by the existing `test_ac08_landing_kinds_do_not_exist` |
| AC-18 | integration | The quote rule (D-3). Chain: `C-AGENT-HUB`. Observable: code, row count, and whether the member receives the task. | Human-approved (D-3) | Each of `start`, `resume` with `null`, an empty string and only spaces → `422 quote_required`, zero rows, and `next` returns nothing. Each other action with a quote → `422 quote_not_allowed`. A secret-shaped quote → `422 secret_in_message` |
| AC-19 | integration | Closed bodies. Chain: `C-AGENT-HUB`. Observable: code and row count, for each action in `AGENT_ACTIONS`. | Human-approved (D-4, D-5) | `{action: "exec"}` → `unknown_action`. An extra field, including `command`, → `bad_agent_body:unknown_field:<n>`. A missing required field, for each. A bad `run` name. A Codex start with `allowed_tools`, `allow_codex` or a cap. `start` with no `refs`, and a non-`start` with `refs`. `ruling` → `message_kind_refused`. An unknown bundle → `missing_blob` |
| AC-20 | unit | `agent_tool_refused` is a closed rule. Observable: its return value. | Human-approved (D-4, D-5) | Refused: `Bash`, `Bash(*)`, `Bash(:*)`, `Bash(<each of AGENT_SHELLS>:*)`, `Bash(codex exec:*)`, `Bash(pwsh -File x:*)`. Accepted: `Read`, `Edit`, `Bash(python -m pytest:*)`. The hub refuses a refused entry with `bad_agent_body:allowed_tools`, zero rows |
| AC-21 | integration | Member start. Chain: `C-AGENT-MEMBER` with a real hub and member on localhost and a `pwsh` shim on `PATH` that records argv. Observable: slot files, `manifest.json`, shim argv and task status. Pinned: order (register, then start); the exact quote; the fields in step 4; the brief under `receipts/fleet-briefs/<run>/`; `.fleet-run/` excluded; no remote in the slot. AC-40 proves the real wrappers accept this layout, which a shim can't. | Human-approved (D-2, D-3, D-4) | Each prerequisite missing gives its reason, in the order listed, and the shim is never called. A second `start` with the same run → `run_exists`. A register exit of 3 → `credits_refused:register:3` and no start call. A token file whose bytes contain a marker: the marker appears in no hub row and no task output |
| AC-22 | integration | The classifier reads the generated file. Chain: real `Get-RunClass` on `.fleet-run/task.md` written by `fleet.py`'s `member_task_md`. Observable: class. | Local Canon (A-4) | `released:human-gate` with `STOPPED:decision` → `decision`. `armed` with `STOPPED:decision` → `unknown`. `Status: DONE` → `done_unverified` |
| AC-23 | integration | Status normalization, pinned to a real export. Chain: real `Get-CreditsRun.ps1 -Export` on a store in the stage, then `fleet.py`'s `normalize_view`. Observable: `run_state`, `stop_class`, `final_status`, `verified`, `final_text`, `outbox`. | Local Canon (A-4) | Every key of `AGENT_RUN_STATES` is walked. An unlisted state → `unknown`. `done_unverified` with no `DONE` → `stopped`. `cancelled` with an unfinished segment → `running`. A `final.md` over `AGENT_FINAL_MAX_BYTES` is cut to the tail |
| AC-24 | integration | `status`, `message`, `stop` for Claude. Chain: `C-AGENT-MEMBER` with the shim. Observable: argv and status. | Human-approved (outline §3 A3) | An unknown run (shim exit 3) → `run_unknown`. A run folder missing → `run_unknown` with the shim never called |
| AC-25 | integration | Resume. Chain: `C-AGENT-MEMBER` with the shim. Observable: `receipts/fleet-briefs/<run>/brief-2.md`, `stop_gate`, argv, and the slot's files. The slot isn't fetched again, and files a run left there survive. | Human-approved (D-3) | A shim exit of 3 → `credits_refused:start:3`. An unknown run → `run_unknown`. A retained receipt with an old `kit_revision`, against a newer `receipts/gate/gate-result.json`, through the real `--check-receipt` → `receipt_stale`, with no brief written, `stop_gate` unchanged and no shim call, and `collect` on that run still works. The hub's quote rule is AC-18 |
| AC-26 | integration | A secret-shaped status doesn't end the member. Chain: `execute_task` → `post_status` → `C-HTTP`. Observable: the status row, the member's process, and its next task. | Local Canon | A `final_text` holding a fake secret → the row has `reason: output_withheld`, no `final_text`, no value in `hub.db` bytes, and a following `ping` completes. Oracle check: without the catch, the same input ends the member process |
| AC-27 | integration | `fleet watch`. Chain: `fleet.py watch` → `cmd_watch` → `cmd_agent` logic → `C-HTTP`, with `--poll` overriding `WATCH_POLL_S`. Observable: exit code and its last line. | Human-approved (D-3) | Done → `0`. Stopped → `7`, with `stop_class`. Unknown → `1`. Rejected → `3`. Member offline → `5`. While `running` it doesn't exit |
| AC-28 | integration | **Live, human row 12.** From SUPER on DUPER, with Mat's words: `agent start` on a throwaway repo; `agent message --kind query` is answered in `outbox` during the run; the run stops with `stop_class: decision` and `fleet watch` exits `7`; `agent resume` with Mat's answer, same session and slot, finishes with `run_state: done`. Observable: `check_live.py agent`. | Human-approved (outline §3 A3 done-when) | `--selftest` feeds a transcript where the session id changed on resume, and one with no query reply, and each must fail. A live start with no quote is refused with `quote_required` |

#### Spec Sufficiency Table

| Behavior | Classification | Resolution |
|----------|---------------|------------|
| Who starts and resumes, and what a question does | Human-approved | D-3 |
| Actions and their surface | Human-approved | Outline §3 A3 |
| Permissions and the tool rule | Human-approved | D-4, D-5 |
| `.fleet-run/task.md` and `done_unverified` handling | Local Canon | A-4: `Get-RunClass` at `Watch-CreditsRuns.ps1:565-684` |
| Shared lane | Local Canon | A-7: `credits_state.py:2310-2313` |
| Removal of `kind_not_enabled` | Human-approved | Plan MVP D-2: "`agent` joins at P4". D-3 enables it, and A-10 removes the code |

#### Files Modified

| File | Action | Summary |
|------|--------|---------|
| `.agent/fleet/fleet.py` | modify | Constants, `validate_agent_task`, `agent_tool_refused`, `execute_agent`, handlers, `normalize_view`, `member_task_md`, `fetch_snapshot`, `cmd_agent`, `cmd_watch`, the catch in `execute_task` |
| `scripts/tests/test_fleet_agent.py` | modify | AC-17 to AC-21, AC-24 to AC-27 |
| `scripts/tests/test_fleet_hub.py` | modify | Delete `test_ac08_agent_kind_is_not_enabled` |
| `core/tools/tests/CreditsFleetMember.Tests.ps1` | modify | AC-22, AC-23 |

### WP-A4: Codex jobs, and remote Claude calling Codex

**Codex on a member.** `.agent/fleet/fleet-tasks.ps1` (new, tracked, copied to `kit/fleet/`) has one `-Action`:

- `CodexStart -Run <run> -Brief <path> -Slot <path> [-ResumeDispatchId <id>]` registers and starts the one-shot S4U
  task `\Fleet\Codex\<run>`, whose action is this script with `-Action CodexRun`.
- `CodexRun` sets `FLEET_CODEX_LOCK` and runs `tools/Invoke-CodexDispatch.ps1 -NonReviewDispatch -ModelClass
  isolated_worker -Mode FullAccess -FullAccessJustification <P-4> -PromptFile <brief> -DispatchId <run>-<n> -WorkingDirectory <slot>`,
  with `-ResumeDispatchId` on a resume. Amended by P-4: this was `-Mode ReviewWorkspace`. The brief's header says to
  read anything and write only in the working folder and the system temp folder (`CODEX_WRITE_SCOPE`).
- `CodexState` prints one JSON line: `running`, plus the last `Status:` line of `final.md`.
- `CodexStop` stops the task. `Remove -Run` unregisters this run's Codex and credits tasks.

`execute_agent` picks the Codex handlers by `body.cli`, saved in `agent/<run>/manifest.json`. A Codex brief uses
the same header, without `.fleet-run/` and without `credits_msg.py`. Prerequisites are `run_exists`, `tool_missing:pwsh`,
`tool_missing:codex` and `kit_missing`. `message` on a Codex run → `codex_no_messages`, because the inbox hook is
Claude-only (outline §3).

**Status (`normalize_codex`).** Task running → `running`. Otherwise the last `Status:` line: `DONE` → `done`, with
`verified: false`; `STOPPED:<class>` → `stopped` with that class; none → `stopped` with `no_status_line`. The exit code
is never read (§2 of the outline: Codex exits 0 with no file written).

**One job at a time (D-5).** When `$env:FLEET_CODEX_LOCK` is set, `Invoke-CodexDispatch.ps1` opens that file with an
exclusive handle for its whole life. If that fails, it exits `CODEX_BUSY_EXIT` with `codex_job_busy`. A Codex job
inherits the variable, so a job calling the wrapper gets busy, which is what stops a Codex job starting another. The
member reads exit `11` through the task's status and reports `codex_job_busy`. When the variable is unset, the wrapper
touches no file and behaves as it does today.

**New control (A-6).** The allow rule below is a prefix, so Claude could otherwise append
`-CodexExecutable <anything>` and run any program. When `FLEET_CODEX_LOCK` is set, the wrapper refuses
`-CodexExecutable` with `codex_executable_refused`, exit 1. A repeated `-Mode` is already a PowerShell binding error, so it
can't turn into `FullAccess`.

**Remote Claude (D-5).** `allow_codex: true` adds exactly two rules to `allowed_tools`:
`Bash(pwsh -NoProfile -File <kit>/tools/Invoke-CodexDispatch.ps1 -Mode ReviewReadOnly:*)` and the same with
`-Mode ReviewWorkspace:*`. The brief says when to use them, and they add `-NonReviewDispatch -AuthorVendor anthropic`
under the default reviewer class. That class can't resume, and D-5's route doesn't need to. No Codex rule exists
without the flag, and `FORBIDDEN_COMMANDS` doesn't change.

#### Boundary Inventory

| Surface | Schema Owner | Field Constraints | Extra-Field Policy |
|---------|-------------|-------------------|-------------------|
| `fleet-tasks.ps1` parameters | PowerShell `param` | `-Action` is a `ValidateSet`; `-Run` matches `NAME_RE` | Binding error |
| `CodexState` JSON | `fleet-tasks.ps1` | `running` bool, `status_line` string or null | `normalize_codex` reads only those |
| `Invoke-CodexDispatch.ps1` environment | The wrapper | `FLEET_CODEX_LOCK` is a local file path | Unset means no change |

#### Acceptance Criteria

| AC | Type | Description | Source | Negative Test |
|----|------|-------------|--------|---------------|
| AC-29 | integration | Codex job start and resume. Chain: `C-AGENT-MEMBER` with the shim, and Pester with `Register-ScheduledTask` mocked. Observable: argv, `def` of the task, and the file on disk. | Human-approved (D-4, P-4, outline §3 A4) | `S4U`; `-NonReviewDispatch`, `CODEX_MODEL_CLASS` and `-Mode FullAccess` with a justification of at least 20 characters naming P-4 (P-4 replaced "no `FullAccess` anywhere in the script"); the brief carries `CODEX_WRITE_SCOPE` before the job. A resume passes `-ResumeDispatchId` with the prior id and the same class. `message` → `codex_no_messages` |
| AC-30 | unit | `normalize_codex` is total. Observable: its result. | Human-approved (D-4) | Every case: running; `DONE`; `STOPPED:decision`; no `Status:` line, with an exit code of 0 → `stopped` / `no_status_line`, never `done`; `Status: done` in the wrong case isn't `DONE`; a malformed class → `stopped` / `no_status_line` |
| AC-31 | integration | The lock and the override refusal. Chain: `C-CODEX` with a stub `codex` on `PATH`. Observable: exit code, stub call count, and the lock file. | Human-approved (D-5); Local Canon (A-6) | A second wrapper while the first holds the lock → exit `11`, `codex_job_busy`, and the stub isn't called. With the lock set, `-CodexExecutable x` → `codex_executable_refused`, and `x` isn't run. A stub job that calls the wrapper gets `11`. With the variable unset: no lock file, and `-CodexExecutable` works as today, by the existing `-CodexExecutable` suites |
| AC-32 | integration | `allow_codex`. Chain: `C-AGENT-HUB`, then `C-AGENT-MEMBER`. Observable: `manifest.json`'s `allowed_tools`. | Human-approved (D-5) | Without the flag, no rule mentions `codex`. With it, exactly the two rules, and neither contains `FullAccess`. `FORBIDDEN_COMMANDS` is unchanged, by a value check |
| AC-33 | integration | **Live, human row 15.** On DUPER, with Mat's words: the AC-28 job finishes on Codex under `workspace-write` (under `FullAccess` after P-4), judged by the file written and the status line; a stopped Codex run resumes between turns. A remote Claude run with `allow_codex` gets a Codex answer, and its attempt with `-Mode FullAccess` appears in `permission_denials`. Observable: `check_live.py codex`. | Human-approved (outline §3 A4 done-when) | `--selftest` feeds an exit-0 job with no file, and a Claude run with no denial, and each must fail |
| AC-40 | integration | The installed kit accepts the member layout. Chain: real `member_kit.py install` into a temp `FLEET_HOME`, then the installed `tools/Invoke-ClaudeDispatch.ps1` and `tools/Invoke-CodexDispatch.ps1`, with stub `claude` and `codex` on `PATH` and a fixture registry holding P-1's binding. Observable: exit code, stub call count and the stub's working directory. Cases: Claude with a brief under `receipts/fleet-briefs/<run>/` and the slot as working directory; a Codex start with `CODEX_MODEL_CLASS`, then a resume of it; D-5's call from a slot with a prompt file in that slot. | Local Canon (A-13, P-1) | A brief outside both roots, and a Codex working directory outside `FLEET_HOME`, are refused and the stub isn't called. A registry without the binding gives `unresolvable_on_harness` and the stub isn't called. A resume on the default class still gives `resume_refused_review_class` |

#### Spec Sufficiency Table

| Behavior | Classification | Resolution |
|----------|---------------|------------|
| Codex permissions, success judged by evidence | Human-approved | D-4 |
| Remote Claude calling Codex, one job at a time | Human-approved | D-5 |
| Lock held by the wrapper | Local Canon | Codex CI/CD doc: no concurrent jobs on one `auth.json`, and A-6 |
| Codex has no mid-run messages | Human-approved | Outline §3 |
| Which class runs a Codex job | Human-approved | P-1 |

#### Files Modified

| File | Action | Summary |
|------|--------|---------|
| `.agent/fleet/fleet-tasks.ps1` | new | Codex task actions, `Remove` |
| `.agent/fleet/fleet.py` | modify | Codex handlers, `normalize_codex`, `allow_codex` rules |
| `.agent/fleet/member_kit.py` | modify | Copies `fleet-tasks.ps1` into the kit |
| `core/tools/Invoke-CodexDispatch.ps1` | modify | `FLEET_CODEX_LOCK` block, `-CodexExecutable` refusal |
| `core/tools/tests/CodexDispatchFleetLock.Tests.ps1` | new | AC-31 |
| `scripts/tests/SetupMember.Tests.ps1` | modify | AC-29's script cases |
| `scripts/tests/test_fleet_agent.py` | modify | AC-29, AC-30, AC-32, AC-40 |

### WP-A5: Results

**Commit identity (P-2, A-14).** `SNAPSHOT_IDENTITY` is removed, and the signature becomes
`make_snapshot(repo, task, identity=None)`, so the MVP's callers keep their form. `None` means `snapshot_identity(repo)`.
The check runs after the existing `no_head` check and before `commit-tree`, so a refusal leaves no commit, and
`fleet.py` names no person's address. This covers `agent start` and the MVP's `run` route.
The checked name and address go into all four `GIT_AUTHOR_*` and `GIT_COMMITTER_*` variables, as `fleet.py:1065` does today, so an inherited variable can't change the commit.

**Order.** Row 7a builds that SUPER half, ahead of the rest of this package, because row 8 sends the first live snapshot
and rows 12 and 15 keep runs for row 17. A base commit under the old fixed identity could never be collected, so no run
may start before this change. No migration is needed.

A member has no git identity of its own, and a job can move the slot's HEAD, so `collect` reads the commit in
`agent/<run>/base` and uses that commit's author. It refuses with `identity_mismatch` if that address fails the suffix
check, or if any commit from `base` to HEAD has another author or committer name or address.

`agent collect` makes a snapshot of the slot with `make_snapshot`: the same temporary index and path check. It does a
`PUT /v1/blobs/<sha>` and completes with `commit`, `tree` and `bundle`, and writes `collected`.

`fleet.py result <member> <run> --repo R` sends `collect`, waits, fetches the blob, checks the hash, runs `git bundle
verify`, fetches into a temporary ref, checks `^{tree}`, refuses `identity_mismatch` if any commit since the run's base
has an author or committer name or address other than `snapshot_identity(R)`, which makes the same refusals, and sets
`refs/fleet/result/<run>` with the zero old-value form.
It prints the commit, the tree and a `git diff --stat` against the run's base, and creates no branch. Landing it on a
branch is a separate step on Mat's word, and the fleet has no code for that. `route_get_blob` already lets the orchestrator
fetch any blob.

`agent drop` calls `fleet-tasks.ps1 -Action Remove` and deletes the run folder and `receipts/fleet-briefs/<run>/`. Credits
rows stay as the audit record.

#### Boundary Inventory

| Surface | Schema Owner | Field Constraints | Extra-Field Policy |
|---------|-------------|-------------------|-------------------|
| `PUT /v1/blobs/<sha>` | `route_put_blob` | Hash must match; `MAX_BLOB_BYTES` | Existing rule |
| Collect status body | `route_post_status` | `refs` fields as strings | Free fields, as in the MVP |
| `refs/fleet/result/<run>` | Git on SUPER | Created only if absent | No branch |

#### Acceptance Criteria

| AC | Type | Description | Source | Negative Test |
|----|------|-------------|--------|---------------|
| AC-34 | integration | `collect`. Chain: `C-AGENT-MEMBER` → `make_snapshot`. Observable: the bundle's contents, status, and the slot's index and HEAD. Includes a new and a changed file. The commit's author and committer equal the `base` commit's. | Human-approved (outline §3 A5, global commit identity rule) | `.fleet-run/` isn't in the tree. A secret-named file → `snapshot_secret_risk:<path>` and no blob. A running or `unknown` run → `run_active`. Slot's HEAD and index are unchanged. A `base` commit whose address fails the suffix check, such as the old `fleet.invalid` identity, → `identity_mismatch`. A job's commit in the slot under another name or address → `identity_mismatch`. `agent start` in a repo that `snapshot_identity` refuses → the same refusal. In each of those, the commit count of the object store shows no new commit and no blob is sent |
| AC-35 | integration | `result`. Chain: `fleet.py result` → `cmd_result` → `C-HTTP`, against a real repo. Observable: refs, tree id, branch list, and exit code. | Human-approved (outline §3 A5) | Tampered blob → `bundle_bad`, no ref. A wrong tree in the status → `tree_mismatch`, no ref. An existing ref → `result_exists`, unchanged. A commit since the base with another author or committer name or address → `identity_mismatch`, no ref. A repo that `snapshot_identity` refuses → the same refusal, no ref. The branch list and `HEAD` are unchanged in every case. No code path in `fleet.py` runs `merge`, `push` or `checkout` against the orchestrator's repo, by a source check |
| AC-36 | integration | `drop`. Chain: `C-AGENT-MEMBER`. Observable: run folder, brief folder, `Remove` call and status. | Human-approved (outline §3 A5) | Before `collect` → `not_collected`. On a running or `unknown` run, or a `cancelled` one with an unfinished segment → `run_active`. Each leaves both folders in place |
| AC-37 | integration | **Live, human row 17.** On Mat's word, one Claude and one Codex result land at `refs/fleet/result/<run>` on SUPER, with their diff shown to Mat and no branch created, and each slot is then dropped. Observable: `check_live.py result`. | Human-approved (outline §3 A5 done-when) | `--selftest` feeds a result with a new branch, one whose tree differs, and one whose commit has an identity other than SUPER's global git identity, and each must fail |
| AC-41 | integration | The SUPER half of commit identity, built in row 7a. Chain: `make_snapshot` → `snapshot_identity`, directly and through `fleet.py run`. Observable: the commit's author and committer, the object store's commit count, refs, and blobs on the hub. Each test sets `GIT_CONFIG_GLOBAL` to its own file, so the test machine's config can't decide the result. The commit carries the repo's name and address, also when the environment sets `GIT_AUTHOR_*` and `GIT_COMMITTER_*` to other values, and `fleet.py` holds no `SNAPSHOT_IDENTITY` and no person's address. | Human-approved (P-2, global commit identity rule) | No global `user.email` or `user.name`, with the repo's set → `identity_missing`. No repo or global value → `identity_missing`. Repo address differing from the global one, both noreply → `identity_mismatch`. Same address with a different name → `identity_mismatch`. Global and repo agreeing on an address that fails the suffix check → `identity_mismatch`. Each leaves no new commit, no ref and no blob. An empty repo still gets `no_head` |

#### Spec Sufficiency Table

| Behavior | Classification | Resolution |
|----------|---------------|------------|
| Temporary index, bundle, non-branch ref, then drop | Human-approved | Outline §1, §3 A5 |
| Landing on a branch | Human-approved | Handoff binding constraint: only on Mat's word. Out of scope here |
| `collect` and `drop` as added actions | Local Canon | A-11: outline §3 A5 needs them, and they use the same task path |
| Snapshot commit identity | Human-approved | Global commit identity rule. P-2 rules SUPER's check, and A-14 records the member's half |

#### Files Modified

| File | Action | Summary |
|------|--------|---------|
| `.agent/fleet/fleet.py` | modify | `collect` and `drop` handlers, `cmd_result`, `make_snapshot` identity, `SNAPSHOT_IDENTITY` removed, `SNAPSHOT_EMAIL_SUFFIX` added |
| `scripts/tests/test_fleet_run.py` | modify | A module-scoped autouse fixture sets `GIT_CONFIG_GLOBAL` to a temporary file holding the fixture identity, so it is in place before the module-scoped `rig` at `:175` starts its member and for as long as that member runs. The fixture repo's address at `:111` takes the same noreply form. The author assertion at `:239` changes from `fleet` to the fixture name and stays an assertion on the produced commit. `COMMITTER` at `:716` commits inside a `run` slot, which never goes through `collect`, so it stays |
| `scripts/tests/test_fleet_agent.py` | modify | AC-34 to AC-36, AC-41 |

### WP-A6: Rules, docs and gates

- `.agent/fleet/bootstrap.md` is relabelled (D-6): the human steps are `BOOTSTRAP_STOPS`. Lines 15-16 change to D-1's wording. The sentence "must never read `member.json`" stays. Setup is
  described as a script run from the orchestrator machine over a local connection, with no host in the file.
- `core/.agent/skills/claude-credits/SKILL.md`: a section on the member route (`launch.auth`, S4U, `gate_project`,
  the hooks limit), which keeps lines 340-343 verbatim, and adds that `CLAUDE_CODE_OAUTH_TOKEN` is a sign-in on Mat's own
  machines, not a misrepresentation of billing (D-1).
- `core/.agent/skills/cli-dispatch/SKILL.md`: `FLEET_CODEX_LOCK`, `CODEX_BUSY_EXIT`, the `-CodexExecutable` refusal,
  `CODEX_MODEL_CLASS` and D-5's route.
- `core/MANIFEST.md` lists `.agent/fleet/member_kit.py`, `.agent/fleet/setup-member.ps1`,
  `.agent/fleet/fleet-tasks.ps1` and `.agent/fleet.json`. The D-13 scrub applies: no LAN address, local machine path or log
  collector product name in tracked files.

#### Boundary Inventory

No external input surface: this package changes documents and a manifest. `template_problems` in
`test_fleet_bootstrap.py` is the owner of the template's shape.

#### Acceptance Criteria

| AC | Type | Description | Source | Negative Test |
|----|------|-------------|--------|---------------|
| AC-38 | unit | `bootstrap.md` and the skills. Observable: `template_problems` and text checks. `BOOTSTRAP_STOPS` holds exactly the three names. The template has no `A human creates each login at this machine's console`. `SKILL.md` still holds lines 340-343 verbatim. | Human-approved (D-1, D-6) | `test_ac19_the_checker_sees_a_removed_stop_line` runs on each new stop. A copy of `SKILL.md` with the billing rule altered fails the check. A copy of the template with `192.168.` fails |
| AC-39 | integration | No new gate failure, and the coverage map holds. Chain: `check_package_gates.py` → `refcheck`, `sanitize --verify`, then the coverage and manifest checks. Observable: its problem list. | Local Canon (plan MVP A-20) | `--selftest` proves that a baseline with a line removed reports a new failure. Every non-live AC has a `test_acNN_*` function in this plan's own test files, or a Pester `It 'AC-N:` case. The MVP's `test_fleet_hub.py` and `test_fleet_run.py` don't count, because they hold their own `test_ac18_*` and others |

#### Spec Sufficiency Table

| Behavior | Classification | Resolution |
|----------|---------------|------------|
| Human steps | Human-approved | D-6 |
| Red baseline comparison | Local Canon | MVP plan A-20 |

#### Files Modified

| File | Action | Summary |
|------|--------|---------|
| `.agent/fleet/bootstrap.md` | modify | Relabelled |
| `.agent/fleet/fleet.py` | modify | `BOOTSTRAP_STOPS` |
| `scripts/tests/test_fleet_bootstrap.py` | modify | `template_problems`, the named assertion |
| `scripts/tests/test_fleet_agent.py` | modify | AC-38 |
| `core/.agent/skills/claude-credits/SKILL.md` | modify | Member route |
| `core/.agent/skills/cli-dispatch/SKILL.md` | modify | Lock and D-5's route |
| `core/MANIFEST.md` | modify | New files |
| `docs/execution/plans/2026-11-04-fleet-agents/check_package_gates.py` | new | Copied from the MVP plan and adapted |
| `docs/execution/plans/2026-11-04-fleet-agents/stage_core.py` | new | Copied from `2026-10-20-review-limits-parameters`; stage `C:/Temp/agentic-framework/fa-stage`; also copies `.agent/fleet/` into the stage for AC-22 and AC-23 |
| `docs/execution/plans/2026-11-04-fleet-agents/run_pester.ps1` | new | Copied unchanged from `2026-10-20-review-limits-parameters` |

### Stop conditions

Execution stops and asks Mat when:

1. The M-1 gate fails on the token (D-2 says A2 stops).
2. Registering or running a task as S4U from the member's own process fails. This is untested, so it's tested first, in row 8.
3. Mat sees a Console charge, or a run shows `auth_mode: api_key_file`. P-3 removed "no plan usage movement".
4. The inbox hook doesn't fire under `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1`.
5. The write test fails under both Codex sandboxes.
6. A step seems to need `CLAUDE_CODE_ENTRYPOINT`, `CLAUDECODE`, `cswap`, a read of `member.json`, or a printed token.
7. A secret value appears in a message, a log or a receipt, including a `gate_token_leak` exit.
8. A live step would touch the log collector or turn off a firewall profile on DUPER.
9. `fleet.py` or `member_kit.py` would need a non-stdlib import.
10. The review cap is reached.
11. The row 0 baseline is red.
12. A step would write `P:/.agent/model-registry.json`, or its hash changed during this plan (P-1).

---

## Out of Scope

| Item | Kind | Deferred-to MEU | Basis |
|------|------|-----------------|-------|
| Cursor and Antigravity | out-of-scope | — | Human-approved: outline §3 "Left out", accepted USER_EXPLICIT 2026-11-04 |
| Member-to-member tasks (P6) | out-of-scope | — | Human-approved: outline §3. The hub still refuses every member task |
| Linux and macOS members | out-of-scope | — | Human-approved: outline §3 |
| Autostart after a reboot | out-of-scope | — | Human-approved: outline §3 |
| Live rulings during a run | out-of-scope | — | Human-approved: outline §3. `ruling` is refused (AC-19) |
| Mail from a member | out-of-scope | — | Human-approved: outline §3. It would put a mail password on the member |
| A separate low-privilege account for agent runs | out-of-scope | — | Human-approved: outline §3 |
| `bypassPermissions` on a member | out-of-scope | — | Human-approved: D-4 |
| A full `/execution-session` on a member, and projects with their own hooks | deferred | — | Human-approved: D-4, "Bounded jobs first". A-3 records the receipt limit |
| Landing a result on a branch | out-of-scope | — | Handoff constraint: only on Mat's word, outside the fleet's code |
| Revoking a Claude token | out-of-scope | — | Human-approved: D-1 records that no revoke route is documented |
| Blob and credits-run retention | out-of-scope | — | Human-approved: MVP plan's Out of Scope and Mat's simplicity rule |
| Pushing `main` or `fleet-mvp`, the MVP's H1-6b refusal, GitHub email settings, D-7's av-kit manifest commit | out-of-scope | — | Each awaits Mat's separate word (handoff) |
| Fixing the existing `refcheck` and `sanitize` failures | out-of-scope | — | MVP plan A-20. Row 0 records them |

---

## BUILD_PLAN.md Audit

This project does not modify build-plan sections, because this package has no `docs/BUILD_PLAN.md` hub. Task row 20
proves the file is absent:

```powershell
python -c "import pathlib,sys; sys.exit(0 if not pathlib.Path('docs/BUILD_PLAN.md').exists() else 1)" *> $env:RECEIPTS_DIR/build-plan-audit.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/build-plan-audit.txt; exit $code
```

---

## Verification Plan

`$env:RECEIPTS_DIR` is `C:/Temp/agentic-framework/receipts`, and `$env:AGENT_MODEL_REGISTRY_HOME` is `P:/.agent`. Set both
before every row. These commands capture exact evidence, so they use no output filter.

### 1. Baseline, row 0

Records the identity, the red `refcheck` and `sanitize` lines, the full pytest gate, and the staged credits suites.

### 2. Targeted tests

```powershell
python -m pytest scripts/tests/test_fleet_agent.py scripts/tests/test_fleet_hub.py scripts/tests/test_fleet_bootstrap.py scripts/tests/test_fleet_run.py -q -rfE *> $env:RECEIPTS_DIR/fa-targeted.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/fa-targeted.txt -Tail 25; exit $code
```

```powershell
pwsh -NoProfile -File docs/execution/plans/2026-11-04-fleet-agents/run_pester.ps1 scripts/tests/SetupMember.Tests.ps1 *> $env:RECEIPTS_DIR/fa-pester-setup.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/fa-pester-setup.txt -Tail 20; exit $code
```

### 3. Staged credits and dispatch suites

The credits suites read filled-in placeholders, so they run from an instantiated stage.

```powershell
python docs/execution/plans/2026-11-04-fleet-agents/stage_core.py *> $env:RECEIPTS_DIR/fa-stage.txt; $code=$LASTEXITCODE; if ($code -ne 0) { Get-Content $env:RECEIPTS_DIR/fa-stage.txt -Tail 10; exit $code }; pwsh -NoProfile -File docs/execution/plans/2026-11-04-fleet-agents/run_pester.ps1 C:/Temp/agentic-framework/fa-stage/tools/tests *> $env:RECEIPTS_DIR/fa-pester.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/fa-pester.txt -Tail 20; if ($code -ne 0) { exit $code }; Push-Location C:/Temp/agentic-framework/fa-stage; python -m pytest tools/tests -k credits -q -rfE *> $env:RECEIPTS_DIR/fa-stage-pytest.txt; $code=$LASTEXITCODE; Pop-Location; Get-Content $env:RECEIPTS_DIR/fa-stage-pytest.txt -Tail 20; exit $code
```

### 4. Package gates, compared with the baseline

```powershell
python docs/execution/plans/2026-11-04-fleet-agents/check_package_gates.py *> $env:RECEIPTS_DIR/fa-package-gates.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/fa-package-gates.txt -Tail 30; exit $code
```

### 5. Live checks, after the human rows

`python docs/execution/plans/2026-11-04-fleet-agents/check_live.py <mode>`, for `setup`, `credits`, `agent`, `codex` and
`result`, each with a receipt named in its row. `--selftest` proves each mode can fail.

### 6. Fresh full gate, H1-2

```powershell
python -m pytest core/tools/tests scripts/tests -q -rfE *> $env:RECEIPTS_DIR/fa-full-pytest.txt; $code=$LASTEXITCODE; Get-Content $env:RECEIPTS_DIR/fa-full-pytest.txt -Tail 25; exit $code
```

---

## Decision Log

D-1 to D-6 are ruled, and their options, precedents and sources are in outline §4. A-1 onward were decided while planning.

```yaml
decision_log:
  - id: D-1
    stage: planning
    question: "How does a member get its logins?"
    resolution: human
    class: source-conflict
    chosen: "Issue on SUPER on Mat's browser approval, store on the member over WinRM in a user-only file, nothing through the hub, for Mat's own account on Mat's own machines only. Claude's token goes through -LaunchHook with CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1. Codex gets a new login per machine. The credential script stays local"
    source_tag: Human-approved
    precedents: ["docs/proposals/2026-11-04-fleet-agents-outline.md §4 D-1"]
    research: { engine: tavily, sources: ["outline §4 D-1"] }
    reasoning: "See the outline"
    human_message_reference: "USER_EXPLICIT 2026-11-04 'all recommendations are accepted'"
  - id: D-2
    stage: planning
    question: "What runs a Claude job on a member?"
    resolution: human
    class: governance-value
    chosen: "The credits engine on the subscription token: launch.auth subscription, S4U, one home install per member. The key route stays the default, and SUPER is unchanged. A2's acceptance includes Mat seeing plan usage move and the Console balance unchanged"
    source_tag: Human-approved
    precedents: ["outline §4 D-2"]
    research: { engine: tavily, sources: ["outline §4 D-2"] }
    reasoning: "See the outline"
    human_message_reference: "USER_EXPLICIT 2026-11-04 'all recommendations are accepted'"
  - id: D-3
    stage: planning
    question: "Who starts and resumes, and what happens on a question?"
    resolution: human
    class: governance-value
    chosen: "Only the orchestrator, only on Mat's chat words. Members use agent-on-user-chat, and SUPER stays human-only. The hub refuses start and resume with no quote. A question stops the run, fleet watch wakes the orchestrator, it asks Mat, and the answer goes in a resume brief, same session and slot"
    source_tag: Human-approved
    precedents: ["outline §4 D-3"]
    research: { engine: tavily, sources: ["outline §4 D-3"] }
    reasoning: "See the outline"
    human_message_reference: "USER_EXPLICIT 2026-11-04 'all recommendations are accepted'"
  - id: D-4
    stage: planning
    question: "What permissions does a member's run get?"
    resolution: human
    class: governance-value
    chosen: "No full bypass. Claude acceptEdits with a per-run allowed list. Codex workspace-write with unelevated, except one elevated try per member, kept if a real write test passes under S4U. Judged by evidence, never exit code. Bounded jobs first"
    source_tag: Human-approved
    precedents: ["outline §4 D-4"]
    research: { engine: tavily, sources: ["outline §4 D-4"] }
    reasoning: "See the outline"
    human_message_reference: "USER_EXPLICIT 2026-11-04 'all recommendations are accepted'"
  - id: D-5
    stage: planning
    question: "May a remote Claude call Codex?"
    resolution: human
    class: governance-value
    chosen: "Yes, through Invoke-CodexDispatch.ps1 only, in its two review modes, one job at a time, when the brief asks. A Codex job started this way can't start another. Not a default gate. FORBIDDEN_COMMANDS unchanged"
    source_tag: Human-approved
    precedents: ["outline §4 D-5"]
    research: { engine: tavily, sources: ["outline §4 D-5"] }
    reasoning: "See the outline"
    human_message_reference: "USER_EXPLICIT 2026-11-04 'all recommendations are accepted'"
  - id: D-6
    stage: planning
    question: "What does setup publish, and what stays a human step?"
    resolution: human
    class: governance-value
    chosen: "Track a setup script with no hosts or credentials. The WinRM connection and credential script stay local. A typed approve line per new machine stays. bootstrap.md is relabelled: browser approvals, the UAC prompt on the first machine, and approve"
    source_tag: Human-approved
    precedents: ["outline §4 D-6"]
    research: { engine: tavily, sources: ["outline §4 D-6"] }
    reasoning: "See the outline"
    human_message_reference: "USER_EXPLICIT 2026-11-04 'all recommendations are accepted'"
  - id: A-1
    stage: planning
    question: "How does the kit get to a member?"
    resolution: autonomous
    class: two-way
    chosen: "Through the existing run task: a tracked .agent/fleet.json, publish, then run kit-install and kit-gate"
    source_tag: Local Canon
    precedents: ["2026-11-03-fleet-mvp AC-22 to AC-30 — hash-checked bundles and named commands"]
    research: { engine: none, sources: [] }
    reasoning: "No WinRM copy and no new hub route, and it carries an uncommitted tree. Flagged to Mat because a snapshot also carries untracked local plan files"
  - id: A-2
    stage: planning
    question: "The M-1 receipt binds to one project path, and each run has its own slot. How does a receipt apply?"
    resolution: autonomous
    class: two-way
    chosen: "An optional --gate-project on --check-receipt, set only by launch.gate_project, allowed only with auth subscription"
    source_tag: Local Canon
    precedents: ["run_gate.py:207-237", "Register-CreditsRun.ps1:261 Assert-Receipt", "Start-CreditsRun.ps1:209 Test-RunReceipt"]
    research: { engine: none, sources: [] }
    reasoning: "A gate per run would cost plan usage on every start. CLI version, user hooks and kit revision are still compared, and the slot's hook digests must equal the gate project's. Flagged to Mat as a control change"
  - id: A-3
    stage: planning
    question: "What about a slot that carries its own .claude/settings.json hooks?"
    resolution: autonomous
    class: two-way
    chosen: "Refuse it, fail closed, until a gate for that hook set exists"
    source_tag: Local Canon
    precedents: ["outline §4 D-4 — bounded jobs first", "run_gate.py check_profile:176-204"]
    research: { engine: none, sources: [] }
    reasoning: "The refusal is what the gate already does. Allowing it would need one gate per hook set, which isn't needed for bounded jobs. A settings file with no hooks is refused too, because its digest differs from a missing file's. Flagged to Mat"
  - id: A-4
    stage: planning
    question: "Monitor classes need a task.md, and DONE needs preflight, capture and seal, none of which exist in a slot"
    resolution: autonomous
    class: two-way
    chosen: "The member writes .fleet-run/task.md, excluded from snapshots. The classifier stays unchanged. done_unverified with DONE reports done, verified false"
    source_tag: Local Canon
    precedents: ["Watch-CreditsRuns.ps1 Get-RunClass:565-684"]
    research: { engine: none, sources: [] }
    reasoning: "It reuses the classifier and states plainly that the evidence is the result bundle. A done_unverified run can't be resumed, so a follow-up is a new run. Flagged to Mat"
  - id: A-5
    stage: planning
    question: "Which hooks go at user level on a member?"
    resolution: autonomous
    class: two-way
    chosen: "credits_inbox.py only, on PostToolUse and Stop, with absolute kit paths"
    source_tag: Local Canon
    precedents: ["core/.claude/settings.hooks.json"]
    research: { engine: none, sources: [] }
    reasoning: "A slot has no armed real plan for stop_gate, and a member has no route to commit for commit_gate. The hook digest is in the receipt, so hooks go in before the gate"
  - id: A-6
    stage: planning
    question: "The allow rule is a prefix. What stops Claude appending -CodexExecutable?"
    resolution: autonomous
    class: two-way
    chosen: "The wrapper refuses -CodexExecutable when FLEET_CODEX_LOCK is set"
    source_tag: Local Canon
    precedents: ["core/.agent/skills/cli-dispatch/SKILL.md:14 — wrapper only"]
    research: { engine: none, sources: [] }
    reasoning: "Without it, D-5's rule would let Claude run any program. Test stubs use a PATH stub for this case"
  - id: A-7
    stage: planning
    question: "One lane or one per run?"
    resolution: autonomous
    class: two-way
    chosen: "Lane fleet for all runs, so one Claude run at a time per member"
    source_tag: Local Canon
    precedents: ["credits_state.py:2310-2313 — lane_busy"]
    research: { engine: none, sources: [] }
    reasoning: "Simplest, and it shares one plan's limits. Parallel runs can come later by changing one value. Flagged to Mat"
  - id: A-8
    stage: planning
    question: "D-4 asks for one elevated try after setup, and the CLI has no setup command"
    resolution: autonomous
    class: two-way
    chosen: "Set the sandbox, run one codex exec write in the elevated WinRM session, then test under S4U. On failure run codex sandbox uninstall and use unelevated"
    source_tag: Research-backed
    precedents: ["codex sandbox --help on 0.166.0 — only uninstall"]
    research: { engine: native, sources: ["https://learn.chatgpt.com/docs/windows/windows-sandbox.md", "https://github.com/openai/codex/issues/34961"] }
    reasoning: "It's D-4's one try, by the only route the CLI offers. It makes machine-wide accounts and network rules, so it's flagged to Mat and reversed on failure"
  - id: A-9
    stage: planning
    question: "BOOTSTRAP_STOPS names steps D-6 no longer makes human"
    resolution: autonomous
    class: two-way
    chosen: "BOOTSTRAP_STOPS as defined, with the named test changes"
    source_tag: Human-approved
    precedents: ["outline §4 D-6"]
    research: { engine: none, sources: [] }
    reasoning: "Follows D-6, and is the code form of its relabelling"
  - id: A-10
    stage: planning
    question: "Keep kind_not_enabled once agent is enabled?"
    resolution: autonomous
    class: two-way
    chosen: "Remove it, and its test"
    source_tag: Local Canon
    precedents: ["fleet.py:106,509", "test_fleet_hub.py:429-434"]
    research: { engine: none, sources: [] }
    reasoning: "No kind would produce it. A dead code in a closed list misleads"
  - id: A-11
    stage: planning
    question: "Outline A3 lists five actions, and A5 needs a way to collect and drop"
    resolution: autonomous
    class: two-way
    chosen: "Two more actions, collect and drop, on the same path"
    source_tag: Local Canon
    precedents: ["outline §3 A5"]
    research: { engine: none, sources: [] }
    reasoning: "No new task kind or route"
  - id: A-12
    stage: planning
    question: "How do the stage's tests reach fleet.py, which isn't in core/?"
    resolution: autonomous
    class: two-way
    chosen: "stage_core.py copies .agent/fleet/ into the stage after --verify"
    source_tag: Local Canon
    precedents: ["docs/execution/plans/2026-10-20-review-limits-parameters/stage_core.py"]
    research: { engine: none, sources: [] }
    reasoning: "AC-22 and AC-23 need a real classifier and a real export next to fleet.py"
  - id: A-13
    stage: planning
    question: "Both wrappers refuse a job's brief, and the Codex wrapper refuses a slot, when the kit is the filled root"
    resolution: autonomous
    class: two-way
    chosen: "Fill PROJECT_ROOT with FLEET_HOME and put briefs under receipts/fleet-briefs/<run>/. No wrapper path check changes"
    source_tag: Local Canon
    precedents: ["Invoke-CodexDispatch.ps1:965-969,991-995", "Invoke-ClaudeDispatch.ps1:698-708", "instantiate.py --verify never compares project_root with --root"]
    research: { engine: none, sources: [] }
    reasoning: "The smallest repair: the wrappers' checks stay whole, and AC-40 proves it with the real wrappers. The kit's other PROJECT_ROOT uses are docs and tools a member doesn't run"
  - id: A-14
    stage: planning
    question: "Snapshot commits carry fleet@fleet.invalid, and the commit identity rule covers every repository"
    resolution: autonomous
    class: two-way
    chosen: "Remove SNAPSHOT_IDENTITY. P-2 rules what SUPER accepts. A member uses the recorded base commit's author and refuses a job commit under another identity. result refuses any other identity. Row 7a builds SUPER's half before the first live snapshot"
    source_tag: Human-approved
    precedents: ["Global commit identity rule", "fleet.py:93-96,1065"]
    research: { engine: none, sources: [] }
    reasoning: "A member has no identity of its own, and a job can move HEAD, so the commit SUPER sent is the only trustworthy source. A base under the old fixed identity could never be collected, so the order matters and needs no migration. Flagged to Mat"
  - id: A-15
    stage: planning
    question: "A kit update must happen while a finished run waits to be collected, and a stopped run may wait across a CLI change"
    resolution: autonomous
    class: two-way
    chosen: "install refuses only when a run's task is Running. Stopped and finished run folders stay. A stopped run keeps its registered receipt, so resume refuses with receipt_stale after a probe-kit or CLI change, and collect and drop still work"
    source_tag: Local Canon
    precedents: ["task row 15 and row 17 order", "the credits store lives under receipts, outside the kit", "Register-CreditsRun.ps1:355-360", "Register-CreditsRun.ps1:337-340", "Start-CreditsRun.ps1:431-447,698-705", "run_gate.py:230-235"]
    research: { engine: none, sources: [] }
    reasoning: "A live task is what a swap can break. A held file also fails the rename, which restores the old kit. Refreshing a retained receipt would bypass what registration checks, so a stated limit with an early refusal is simpler. Flagged to Mat"
  - id: P-1
    stage: planning
    question: "Which class runs a fleet Codex job, and where is its Codex binding?"
    resolution: human
    class: governance-value
    chosen: "isolated_worker, bound on codex-cli only in the registry copy carried to a member. The slug comes from the reviewer binding at copy time. SUPER's registry is never written"
    source_tag: Human-approved
    precedents: ["Invoke-CodexDispatch.ps1:595-600", "ModelRegistry.psm1 Import-CompiledOverlay", "scratch-copy probe: zorivest and av-kit refuse with overlay_not_validated on a changed registry"]
    research: { engine: none, sources: [] }
    reasoning: "Mat first chose editing SUPER's file on a brief that said it touched nothing on SUPER. The probe then showed 9 projects would refuse dispatch and 8 repos would need a commit, and Mat changed the ruling"
    human_message_reference: "USER_EXPLICIT 2026-11-04 'Member-only (Recommended)', changing 'add 60M tokens, P-1 (a)'"
  - id: P-2
    stage: planning
    question: "What identity may a snapshot commit carry?"
    resolution: human
    class: governance-value
    chosen: "The repo's effective user.name and user.email must equal the global git config, and the address must end with SNAPSHOT_EMAIL_SUFFIX. fleet.py names no person's address"
    source_tag: Human-approved
    precedents: ["Global commit identity rule: the global user.email holds the noreply address and isn't overridden in a repository", "read-only check 2026-11-04: all 33 repos under P:/ match their global identity", "review round 3, F-005"]
    research: { engine: none, sources: [] }
    reasoning: "A suffix alone accepts another person's noreply address and any name. Comparing with the global config enforces the rule from where the rule says it lives, with one small check and no address in public code"
    human_message_reference: "USER_EXPLICIT 2026-11-04 'c, P-2 recommended, 2 more rounds'"
  - id: P-4
    stage: execution
    question: "Codex's Windows sandbox can't write under a fleet S4U task. How does a Codex job run?"
    resolution: human
    class: governance-value
    chosen: "Direct Codex jobs run the wrapper's FullAccess mode with a fixed justification, and the brief limits writes to the working folder and the system temp folder. A Claude job's Codex call keeps the two sandboxed modes (D-5, AC-32 unchanged). Setup's Codex test is a full-access write; the sandbox result is recorded only"
    source_tag: Human-approved
    precedents: ["core/.agent/skills/cli-dispatch/SKILL.md:61 — FullAccess for a reproduced sandbox capability failure", "stop condition 5"]
    research: { engine: native, sources: ["https://github.com/openai/codex/issues/38665", "https://github.com/openai/codex/issues/13887"] }
    reasoning: "Under S4U on DUPER, every sandboxed pwsh exits 0xC0000142 and apply_patch fails; only cmd redirects write, so setup's pass depended on the model's quoting. One full-access write under the same task passed. Amends D-4's 'Codex workspace-write'"
    human_message_reference: "USER_EXPLICIT 2026-11-05 'i don't mind this since the guardrails and other instructions are very explicit about read actions and write only into temp', then 'I agree and approve, proceed'"
```

D-1 to D-6 and P-1 to P-4 are ruled. A-1 to A-15 passed the obviousness test. Each is two-way, so Mat can reverse any of them at the
plan gate, and the ones a reader might want to change are flagged in User Review Required.

**P-1 is ruled: member-only.** Rejected: editing SUPER's registry, which stops dispatch in 9 projects until each
re-syncs and needs a commit in 8 repos; a compiled overlay on each member, which is more machinery; and no Codex resume,
which narrows outline A4.

**P-2 is ruled: compare with the global git config.** Rejected: writing the exact identity into tracked config, which
puts it in the public repo and needs a field in each repo; and the suffix check alone, which accepts another person's
noreply address. The limit: a global config changed to another noreply address passes.

**P-3 is ruled during execution: no meter proof on the Ultra account.** Row 8's jobs came to about $11.66 at list price,
and the weekly meter still showed 27%. Mat's words: "1% takes few hours of agentic work so we will drop proving that on the Ultra account. Free accounts do not offer claude code so we will just accept what we have with pretty high degree of certenty that everything works as it should." In place of the
readings, row 8 rests on a one-turn stream test of DUPER's token: `apiKeySource: none`, a `seven_day` window at `0.27`
resetting Sunday Nov 8 at 6:00 AM, as on Mat's Usage page, and `isUsingOverage: false`. The limit: nobody saw the meter
move, and the Console wasn't read again after the runs, so a later Console charge still fires stop condition 3.

**P-4 is ruled during execution: fleet Codex jobs run with full access.** Stop condition 5 fired on row 3's rerun.
Under the S4U task, every sandboxed `pwsh` exits `0xC0000142` and `apply_patch` reports "Failed to write file", in
both sandboxes and since the first run. Only a `cmd` redirect writes, so the 13:42 pass came from how the model quoted
one command, and the reboot changed nothing. One write under `danger-full-access` and the same task passed
(`fa-codex-fullaccess-probe.txt`). Mat's words: "i don't mind this since the guardrails and other instructions are
very explicit about read actions and write only into temp", then "I agree and approve, proceed". Rejected: Codex jobs
on SUPER only, which drops outline A4 on members, and keeping `cmd` as the only writer. The limit: no sandbox enforces
the write scope. Only the brief does, and a job can read anything the member's user can, including the stored token.

---

## Research References

- `docs/proposals/2026-11-04-fleet-agents-outline.md`: rulings, tests on DUPER, and sources
- `docs/execution/plans/2026-11-03-fleet-mvp/implementation-plan.md`: definitions and chains this plan extends
- `docs/proposals/2026-11-01-remote-hosts.md`: reference only, `launch.auth` and live-ruling limits
- `core/.agent/skills/claude-credits/SKILL.md:340-343`, `core/.agent/skills/cli-dispatch/SKILL.md:14,47`
- https://code.claude.com/docs/en/authentication and https://code.claude.com/docs/en/env-vars: `setup-token`, subprocess scrub
- https://code.claude.com/docs/en/permission-modes: `acceptEdits`, `--allowedTools`
- https://code.claude.com/docs/en/legal-and-compliance: limits behind D-1 and D-6
- https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan: `claude -p` draws from plan limits
- https://learn.chatgpt.com/docs/auth and https://learn.chatgpt.com/docs/auth/ci-cd-auth: one `auth.json` per serialized stream
- https://learn.chatgpt.com/docs/windows/windows-sandbox.md and https://github.com/openai/codex/issues/34961: sandbox modes, exit-0 symptom
- https://learn.microsoft.com/en-us/windows/win32/taskschd/security-contexts-for-running-tasks: S4U
- https://git-scm.com/docs/git-bundle and https://git-scm.com/docs/git-update-ref: bundles, zero old-value form

## Validation stage contract

| Stage | Command | cwd | Scope | Blocking | Expected |
|---|---|---|---|---|---|
| Static | `python core/tools/lint_task_contract.py --task docs/execution/plans/2026-11-04-fleet-agents/task.md` | repo root | Task contract | Yes | Pass |
| Targeted | Verification Plan §2 | repo root | Fleet test files, setup Pester | Yes | Pass |
| Staged | Verification Plan §3 | repo root, then stage | Every Pester suite and the credits pytest, instantiated | Yes | Pass |
| Package | Verification Plan §4 | repo root | `refcheck`, `sanitize --verify` against the baseline; AC-to-test coverage | Yes | No new failure |
| Fresh full | Verification Plan §6 | repo root | `core/tools/tests`, `scripts/tests` | Yes | Pass |
| Runtime | Verification Plan §5 | repo root, on SUPER, with hub and member running | Live DUPER | Yes, for AC-5, AC-16, AC-28, AC-33, AC-37 | Pass, from the receipts named in each row |

Native shell: PowerShell, with Python 3.14 on SUPER. Input identity for evidence is the SHA-256 of `git rev-parse HEAD`,
`git status --porcelain` and `sys.version`, computed independently at H1-6b. Intermediate evidence is not reused: the
final review follows one fresh full gate.
