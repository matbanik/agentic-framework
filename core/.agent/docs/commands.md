# {{PROJECT_NAME_TITLE}} Commands & Operational Reference

> Relocated from AGENTS.md (2026-06-13 instruction-set-optimization slim). Operational reference: Quick Commands, Skills index, MCP Servers, Context & Docs, RTK.
>
> Command lines below show tool argv only. Route and capture them through the
> [RTK section below](#rtk-rust-token-killer---token-optimized-commands) when RTK
> is installed, and through `.agent/docs/output-evidence-policy.md` always.
> Redirect every process stream to `{{RECEIPTS_DIR}}`. A failing child must leave
> every diagnostic id on that receipt (full-failure receipt; compact display must
> not drop the second error).


## Quick Commands

> The following fenced block is an argv-only reference block. Route every selected
> argv through the canonical receipt policy before execution.

```bash
# Environment (run once per session, before the first redirect or dispatch)
bash tools/preflight.sh                # 8 prerequisite checks; exit 1 names the failures
bash tools/preflight.sh --phase build  # skip the codex/pwsh checks when no review is planned

# Validation — D6_ADOPTER_ARGV (from PROJECT-PROFILE.md Block D)
# There is no packaged tools/validate_codebase.py. Register the adopter's
# executable + argv, cwd, scope, blocking, expected result, shell, and receipt
# in PROFILE D6. Example (not a universal default):
python -m pytest test_hello.py -q
# Missing executable and failing children must exit nonzero; the receipt keeps
# every diagnostic id (do not compact away the second failure).
# In a lane worktree, run the same D6 argv as a registered, contained child of
# the lane card: python tools/lanes.py gate run --worktree <path> -- <D6 argv...>
# The governed land (tools/lanes.py land prepare, step 5) gates the candidate
# tree with the adopter-supplied tools/validate_codebase.py; an adoption that
# runs lanes ships that script (ADOPTION-GUIDE.md "Parallel lanes").

# MEU Status SSOT
uv run python tools/meu_status.py list --status pending --unblocked  # Next unblocked work
uv run python tools/meu_status.py next                              # Top 5 unblocked MEUs
uv run python tools/meu_status.py stats                             # Summary counts
uv run python tools/meu_status.py update <row_key> <status>         # Update status
uv run python tools/meu_status.py render --check                    # CI drift gate

# Issue Triage (known-issues.yaml SSOT)
uv run python tools/issue_triage.py stats                            # Issue counts
uv run python tools/issue_triage.py list --json                      # All issues (machine)
uv run python tools/issue_triage.py list --severity critical         # Filter by severity
uv run python tools/issue_triage.py get <ISSUE-ID>                   # Single issue details
uv run python tools/issue_triage.py add --id <ID> --title <T> --severity <S> --component <C>  # Record new
uv run python tools/issue_triage.py verify                           # Flag stale (>30d)
uv run python tools/issue_triage.py verify --deep                    # Deep verify: file checks, test coverage
uv run python tools/issue_triage.py render                           # Regenerate markdown
uv run python tools/issue_triage.py bucket                           # Group issues into proposed MEU batches
uv run python tools/issue_triage.py triage                           # Generate triage-output.yaml
uv run python tools/issue_triage.py triage --output <PATH>           # Generate to custom path
uv run python tools/issue_triage.py discover --dry-run               # Scan for TODO/FIXME/HACK (preview)
uv run python tools/issue_triage.py discover                         # Scan and persist candidates
uv run python tools/issue_triage.py discover --root <DIR>            # Scan specific directory
uv run python tools/issue_triage.py promote <ID>                     # Promote candidate → open
uv run python tools/issue_triage.py dismiss <ID>                     # Dismiss candidate → dismissed
uv run python tools/issue_triage.py render --include-candidates      # Render with candidate section
uv run python tools/issue_triage.py resolve <ID> --resolution <TEXT> [--meu <MEU-ID>]  # Close an issue: status resolved, the resolution text and today's resolved date (--meu appends a meu_links entry); the lane integrator's ki-close request runs this verb

# Session wait (one wait script, named conditions)
uv run python tools/session_wait.py check --cond plan_done:<plan> --cond lanes_free   # One line: hold, or each reason why not
uv run python tools/session_wait.py wait --name <id> --plan <plan> --owner <session> --cond <cond> --direction-session <session> --direction-message <uuid> --direction-quote "<quote>"   # Background wait: wait_ok 0, wait_timeout 5
uv run python tools/session_wait.py list                             # Who waits for what
uv run python tools/session_wait.py use --name <id>                  # fired -> used, one time

# Executor worktrees and lanes (execution-session.md §4; git-workflow/SKILL.md §Lane Commits)
uv run python tools/executor_worktree.py create <slug> [--branch lane/<slug>] [--base <rev>] [--carry <path>]... [--lane-plan <plan dir> [--session <id>]]  # Executor worktree: a git worktree under `{{PROJECT_ROOT}}-wt/<slug>` on its own branch `lane/<slug>` (made at the base and checked out; `--branch` takes only that name, `worktree_bad:branch`; an existing `lane/<slug>` refuses `worktree_bad:branch_exists`) with its own venv and the carried uncommitted paths, the tree of record for one executing session; the standard carry set is the plan folder plus .agent/context/meu-status.yaml, .agent/context/meu-registry.md and .agent/context/current-focus.md; prints worktree_ready:<path> or worktree_bad:<reason> and leaves nothing behind on a refusal; `--lane-plan` (the default route) runs `tools/lanes.py claim` for the plan after the build (a refusal prints worktree_bad:claim:<reason>); under `.agent/lane-route.json` `required: true` only an `exempt` slug may leave it out (worktree_bad:no_plan); a run-identity worktree (`create <run-id> --run-id <run-id> --op <op> --plan <slug>`) keeps the old route
uv run python tools/executor_worktree.py check <worktree>                         # Before every gate run inside the worktree: worktree_ok, or worktree_bad:<reason> (unlisted, manifest, baseline, overlay_crlf, link:<name>, venv, env, case:<rel>)
uv run python tools/executor_worktree.py land <worktree>                          # Run from the main tree (cwd on the main tree, never inside the worktree): writes the worktree's changes since its baseline onto the main tree under the gate lease; land_ok:<A>:<M>:<D>; land_fail:busy:<pid> is an ordering wait; land_fail:exists|missing|changed|case|shape:<rel> names the path to sync first
uv run python tools/executor_worktree.py sync <worktree> <rel>...                 # Pulls the main tree's version of each named file into the worktree and its baseline, so the next land no longer collides on it; sync_ok:<rel> or sync_fail:ignored|case|shape:<rel>; nothing is written when any path is refused
uv run python tools/executor_worktree.py remove <worktree> [--discard]            # Run from the main tree after land: removes the worktree, its baseline ref and its branch `lane/<slug>` when the tip is an ancestor of `main`; worktree_removed:<path>; refuses worktree_bad:unlanded unless --discard abandons the unlanded work and deletes the branch too; a stage-1 manifest without a `lane/<slug>` branch deletes no branch
uv run python tools/lanes.py ownership-check --task <task.md>  # create-plan Step 4, before the Step 5 review: checks the task's Lane Ownership section with the claim's rules; ownership_ok, or ownership_bad:<reason> (no_ownership, owns_overlap:<entry>, owns_junction:<entry>, ...), exit 1
uv run python tools/lanes.py ownership-check --grouping <file>  # session-grouping, before the proposal: checks the Session Ownership section; ownership_ok, or one overlap:<tier>:<a>:<b>:<entry> line for each same-tier pair that shares a path, or ownership_bad:<reason>, exit 1
uv run python tools/lanes.py list                                                 # At session start: the lane cards, any stale card and any HALT
uv run python tools/lanes.py claim --plan <plan dir> --worktree <path> --session <s>  # Claim the lane of a task with a `## Lane Ownership` section; refused: <reason> on a refusal
uv run python tools/lanes.py beat --plan <plan dir> --session <s>                 # At every task-row boundary; exit 3 is HALT, card_superseded stops the session
uv run python tools/lanes.py commit --worktree <path> --message-file <file> [--generation <g>]  # The lane commit helper (D-1, `git-workflow/SKILL.md` §Lane Commits): commits the staged change on the caller's own `lane/<slug>` with the hooks and no prompt; session from {{PROJECT_NAME_UPPER}}_SESSION; commit_ok:<sha>, or commit_fail:<reason> / refused: <reason>, exit 1
uv run python tools/lanes.py land prepare --worktree <path> --l0 <sha> --message-file <file> [--op <id>]  # Land steps 1-5: freeze the lane at L0, rebase it onto pinned main in a disposable candidate, apply the handoff's Integration requests, keep and gate the tree T; prints land_review:* lines and land_ready:<op>:<tree>; land_conflict:<paths> and owns_violation:<path> set the card back to active
uv run python tools/lanes.py land prepare --op <id> --verdict <file>  # Records the reviewer verdict on the ready land, bound to tree(T); land_verdict:<op>:<tree>:approved
uv run python tools/lanes.py land publish --op <id> (--grant | --human-directed --session <s> --message-uuid <u>)  # Land step 6 onward: publishes T as one main commit C through tools/commit_batch.py, then moves the main tree to C; land_published:<op>:<C> and land_closed:<op>; with neither authority it refuses needs_human_publish; never pushes; Windows-only in stage 2 (land_unsupported_platform elsewhere)
uv run python tools/lanes.py land recover --op <id>  # Re-runs a land op from its journal under the per-op recovery lease; exit 3 op_busy when another process holds the lease (an ordering wait, nothing written)
uv run python tools/lanes.py release --plan <plan dir> --session <s>              # At closeout of a lane without its own branch: releases the card
uv run python tools/lanes.py release --worktree <path> --reset [--session <s>]  # After land_closed, and only after the executor worktree is removed: moves lane/<slug> from L0 to the landed C (read-tree -m -u, update-ref with the old value) and releases the card; without --reset a landing card with a live worktree refuses release_unreset
uv run python tools/lanes.py gate run --worktree <path> -- <argv...>  # Runs a gate command as a registered, contained child of the lane card and exits with the child's code; refuses deps_pending while a deps claim is pending
uv run python tools/lanes.py deps begin --worktree <path> [--wait-s <0-3600>]  # Before a dependency change: sets the pending deps claim, drains every registered gate (deps_wait:<lane>:<pid> lines), then deps_exclusive:<lane>; refuses deps_drain_timeout:<count> after the wait and clears its claim
uv run python tools/lanes.py deps end --worktree <path>  # After the dependency change: clears the lane's deps claim; deps_cleared
uv run python tools/result_snapshot.py take --clone <clone> --run <run>  # Replay route (MEU-949): snapshots the scratch clone's working tree as refs/fleet/result/<run> in the clone (temporary index, no hooks, no signing; the clone's index, HEAD and files stay); snapshot_ok <run> base=<B> commit=<S> tree=<T>; refuses snapshot_bad:<reason> (run, not_clone, exists, empty), exit 1
uv run python tools/result_snapshot.py fetch --clone <clone> --run <run> [--session <s>] [--author-vendor <v>] [--status <status.json>]  # Fetches the result ref into the main repository and writes the ledger <git common dir>/{{PROJECT_NAME}}-results/<run>.json (result-ledger/1); --status sets author_vendor from the worker dispatch's cli (claude anthropic, codex openai; vendor_conflict against --author-vendor); fetch_ok <run> commit=<S>
uv run python tools/result_snapshot.py scope --run <run> [--gate-run <dir>]  # From the main tree after lanes.py land replay: one scope_item lock|record|correction|context line per item C holds that no reviewer read, then one void <kind> <reason> line per review whose key no longer matches (also written to <run>/events.jsonl); integration_review:none when there is none (MEU-950)
uv run python tools/result_snapshot.py brief --run <run> --out <file> --dispatch-dir <dir>  # Writes the integration review prompt (range-diff B..S against P..C, the scope items, the sessions landed between B and P with their write sets and public names) and the review-seen.v1 record <out>.seen.json of its input (run, P, C tree, plan, dispatch_dir); <dir> is the <OutputDir>/<DispatchId> of the integration review dispatch, which brief does not make and which no other seen record names (brief claims it); brief_ok <run> out=<file>, brief_seen <run> seen=<out>.seen.json, then one dispatch <delta>[,<delta>] -AuthorVendor <vendor> line per author vendor; refuses snapshot_bad:exists when the seen record is there, dispatch_missing (no --dispatch-dir), seen_late (<dir> is there: its dispatch started), dispatch_claimed (another seen record claimed <dir>), dispatch_bad (<dir> is not one canonical spelling: a name part ends in a dot or a space, or its last part is not a -DispatchId) (MEU-950, EA-39 to EA-42)
uv run python tools/result_snapshot.py seen --clone <clone> --out <file> --dispatch-dir <dir>  # Before the worker review dispatch: records the clone's working tree as refs/fleet/seen/<commit> on B (in the clone and the main repository) and writes the review-seen.v1 record <file>, which names <dir>, the <OutputDir>/<DispatchId> of that review dispatch (seen does not make it; it claims it, so no other seen record can name it); seen_ok clone=<clone> tree=<tree> out=<file>; refuses snapshot_bad:exists, not_clone, dispatch_missing (no --dispatch-dir), seen_late (<dir> is there: its dispatch started), dispatch_claimed (another seen record claimed <dir>) or dispatch_bad (<dir> is not one canonical spelling: a name part ends in a dot or a space, or its last part is not a -DispatchId) (EA-39 to EA-42)
uv run python tools/result_snapshot.py review --run <run> --kind worker|integration --verdict <file> [--seen <file>]  # Records an approved review-verdict.v1 file as a review event of the run, keyed by the input in its seen record (worker: the tree of the seen record of result_snapshot.py seen; integration: (P, C tree) of the <out>.seen.json of brief); review_ok <run> <kind> <key>; a new seen record keys only <dir>/final.json of its dispatch folder, written after the record; refuses snapshot_bad:verdict_bad, seen_missing (no --seen and no verdict recorded before), seen_used (another verdict used the record), seen_bad (the record is not of this run and kind, or names no dispatch_dir), seen_dispatch (the verdict is not <dir>/final.json of the record), seen_stale (the verdict is older than the record), dispatch_used (another seen record used the folder), seen_bad (no seen record claimed the folder) or dispatch_claimed (two claims name the folder, or its claim is of another seen record) (MEU-950, EA-39, EA-40, EA-42)
uv run python tools/result_snapshot.py drop --run <run>  # Deletes refs/fleet/result/<run> in the main repository and in the clone; the ledger and the event file stay; drop_ok <run>
uv run python tools/lanes.py land replay --snapshot refs/fleet/result/<run> --task <task.md> [--check-only | --sync <batch>]  # Replays B..S onto the main HEAD P in a disposable gate candidate, checks the task's owns, applies the integration requests and writes <run dir>/replay-batch.json; replay_ready <run> parent=<P> tree=<T> batch=<path>; land_conflict:<paths> or replay_bad:<reason> writes nothing to main; --sync writes the batch into the main working files (replay_synced <run> paths=<n>) (MEU-949)

# Land journal and reconcile (MEU-952, MEU-953)
uv run python tools/land_journal.py [--repo <main>] status  # MEU-953: one `land_journal <run> <last step> <crash state>` line per journal in <git common dir>/{{PROJECT_NAME}}-land-journal, then `journal_stop <run>` and `final_validation <run>` when they are there; exit 2 on a bad journal (`journal_bad:<line>`)
uv run python tools/land_journal.py [--repo <main>] recover --run <run>  # MEU-953: does the one action of the run's crash state, once (1 land again, 2 move the ref, 3 record the facts, 5 sync the index, 6 records, audit and close); state 4 writes STOP and exits 3; a live process that lands the run (any carrier: the `<run>.drive.lock` lease) refuses `land_live:<run>`, exit 4; `land_journal_recovered <run> <state>`
uv run python tools/land_journal.py [--repo <main>] stop --run <run> --reason <one line>  # MEU-953: writes STOP (a human-held stop); while STOP is there, `lanes.py land` and `commit_batch.py` refuse `land_blocked:journal_stop:<run>` (a journal synced but not closed refuses `land_blocked:sync_pending:<run>`); `journal_stop <run>`
uv run python tools/land_journal.py [--repo <main>] clear-stop --run <run> --session <s> --message-uuid <u>  # MEU-953: removes STOP only on the typed human ruling `Clear the land stop of <run>.` read from the transcript record, and appends the ruling to cleared.jsonl; `stop_cleared <run>`, or `land_journal_refused:<reason>` (exit 1)
uv run python tools/replay_reconcile.py brief --request <reconcile-request.json>  # MEU-952: writes reconcile-brief.json (reconcile-brief/1) beside the request: the base P, the conflict paths and each side's run, session, author vendor, commit, handoffs, intents and test ids; `reconcile_brief <path>`
uv run python tools/replay_reconcile.py prepare --request <file> --clone <reconciler clone>  # MEU-952: writes the second side's change set into the clone at P (the side's bytes, or the `git merge-file` result with its conflict markers) and records the prepared bytes; `reconcile_prepared <clone> conflicts=<n>`
uv run python tools/replay_reconcile.py check --request <file> --clone <reconciler clone>  # MEU-952: reads <clone>/reconcile-report.json (`verdict`, `session`, `notes`); `reconcile_ok cannot_keep_both:<session>`, or for `both_kept` one `reconcile_delta <path>` line per delta path and `reconcile_ok both_kept`; refuses conflict markers, a delta path in the deny set and a test id of either side that the clone does not collect (`reconcile_bad:<reason>`, exit 1, with a WARN record for a denied path)
uv run python tools/replay_reconcile.py record --request <file> --clone <reconciler clone> --run <run> --author <reconciler session> --author-vendor <vendor>  # MEU-952: writes <common>/{{PROJECT_NAME}}-results/<run>/reconcile.json (reconcile-record/1), which `result_snapshot.py scope` reads for the `scope_item reconcile` lines; `reconcile_recorded <path>`

# CLI dispatch: resume and fork (.agent/skills/cli-dispatch/SKILL.md §Resume and Fork)
pwsh -NoProfile -File tools/Invoke-CodexDispatch.ps1 -ModelClass <non-review class> -NonReviewDispatch -ResumeDispatchId <id> | -ForkDispatchId <id> -DispatchId <new> ...  # Continue (resume) or branch (fork) the Codex session recorded in <OutputDir>/<id>/status.json session_id; the switches are exclusive; review classes, -Kind and -LoopId dispatches refuse both (resume_refused_review_class); every refusal is named resume_* on stderr, exit 1, before any launch. POSIX: tools/Invoke-CodexDispatch.sh --ResumeDispatchId|--ForkDispatchId
pwsh -NoProfile -File tools/Invoke-ClaudeDispatch.ps1 -ModelClass <class> [-ResumeDispatchId <id> | -ForkDispatchId <id>] -ValidateOnly ...  # Headless Claude through the wrapper (registry class for the claude-p harness, --session-id recorded in status.json); -ValidateOnly checks the arguments, paths and continuation source and prints dispatch_args_ok without launching claude; same resume_* refusals as the Codex wrapper

# Coordination events (wait records and the stage 3 metrics, MEU-943)
uv run python tools/coordination_events.py record --kind <kind> --session <session> --plan <plan> --row <row> --reason <code> --scope <resource> [--blocker <holder>] [--outcome <outcome>]   # One record; exit 2 and record_invalid <field> on a bad field
uv run python tools/coordination_events.py report --log <events.jsonl> [--hook-log <hook-log.jsonl>] [--as-of <ts>] [--json]   # One line per metric, or one JSON object

# Gate platform classes
uv run python tools/gate_platform.py show --json   # Stage and test platform classes (read-only JSON)
uv run python tools/gate_platform.py check         # Fails on a stage with no class

# Development (current scaffold)
pytest --cov=packages/core --cov-report=term            # Coverage (advisory)

# Planned scaffold commands (run only after the package exists)
# uv run fastapi dev packages/api/src/{{PROJECT_NAME}}_api/main.py  # API
# npx tsc --noEmit                                          # TypeScript type check
# npx vitest run                                            # TypeScript unit tests
# npx eslint <ts-package>/src --max-warnings 0              # TypeScript lint
# npm run dev                                               # Electron UI
```


## Skills

| Skill | Path | Purpose |
|-------|------|---------|
| Git Workflow | `.agent/skills/git-workflow/SKILL.md` | Agent-safe git operations with SSH commit signing. Prevents interactive prompt hangs. |
| Codebase Quality Gate | `.agent/skills/quality-gate/SKILL.md` | Validation pipeline: type checks, linting, tests, anti-placeholder scans, evidence checks. Supports phase-level and MEU-scoped runs. |
| MEU Status SSOT | `.agent/skills/meu-status/SKILL.md` | Query, update, and render MEU completion status via the central YAML SSOT. Replaces manual edits to meu-registry.md and BUILD_PLAN.md status tables. |
| Pre-Handoff Review | `.agent/skills/pre-handoff-review/SKILL.md` | Self-review protocol addressing 10 recurring patterns from critical review analysis. Reduces average review passes from 4-11 to 3-5. |
| Terminal Pre-Flight | `.agent/skills/terminal-preflight/SKILL.md` | Mandatory pre-flight checklist for terminal commands. Enforces the redirect-to-file pattern to prevent PowerShell buffer saturation and session hangs. |
| Completion Pre-Flight | `.agent/skills/completion-preflight/SKILL.md` | Mandatory pre-flight checklist before stop/report events. Enforces task.md re-read gate and post-truncation recovery sequence to prevent premature stop. |
| Completion Timestamp | `.agent/skills/timestamp/SKILL.md` | Generate the canonical completion timestamp from the system clock using the skill's registered exact-receipt command; do NOT derive time from UTC tool response headers. |
| Issue Triage | `.agent/skills/issue-triage/SKILL.md` | Record, query, verify, and manage known issues via the YAML SSOT (`known-issues.yaml`). Use when discovering bugs or reviewing issue status. |
| Subagent Delegation | `.agent/skills/subagent-delegation/SKILL.md` | In-harness subagent detection + delegation gate (Claude Code `.claude/agents/`). Resolves `fresh_worker`, routes eligible `task.md` rows to `{{PROJECT_NAME}}-builder`/`{{PROJECT_NAME}}-verifier`, and enforces the never-delegate categories. |
| CLI Dispatch | `.agent/skills/cli-dispatch/SKILL.md` | External CLI routing: the Codex wrapper and the headless Claude wrapper (`tools/Invoke-ClaudeDispatch.ps1`), with session resume and fork. Isolated workers run on headless Claude through the wrapper; independent review follows the chain in `.agent/docs/model-routing.md`. |
| Deep Research Prompting | `.agent/skills/deep-research-prompting/SKILL.md` | Portal-ready deep research prompt procedure: Pomera MCP preflight hard gate, provider capability recon query bank (Tavily/Exa routing), 14-day capability snapshots, D1/D2/D3 prompt templates, triangulation synthesis. Driven by `/inspiration-research`. |
| Session Wait | `.agent/skills/session-wait/SKILL.md` | One wait script with named conditions and one wait record. A wake-up carries no authority. |
| 1M Context Switch | `.agent/skills/context-1m/SKILL.md` | Claude Code only, human-invoked: `/context-1m on\|off\|status` sets or removes `env.CLAUDE_CODE_DISABLE_1M_CONTEXT` in `~/.claude/settings.json` for every session on the machine. Installed into `~/.claude/skills/` (`ADOPTION-GUIDE.md` §1M context switch). |
| Expert Pass | `.agent/skills/expert-pass/SKILL.md` | The packet for one expert pass on a set of briefs (HDP §5a). The reviewer reads only, and asks the three questions. |

## MCP Servers

| Server | Purpose | Verify With |
|--------|---------|-------------|
| `text-editor` | Hash-based conflict-safe editing | `get_text_file_contents` |
| `sequential-thinking` | Complex multi-step analysis | `sequentialthinking` |


## Context & Docs

- **How development works end-to-end** → `.agent/docs/development-lifecycle.md` — the 9-phase lifecycle (inspiration → committed code), human-intervention map, and infrastructure map. **Source of truth for the process.** Its narrative companion `.agent/docs/agentic-methodology.md` covers the *why* (philosophy, economics, design rationale). Read the lifecycle doc when onboarding to the workflow or when you need the full process map.
- **Harness capability profiles** → `.agent/docs/harness-profiles.md` — capability flags (`role`, `plan_to_exec_gate`, `injects_auto_approval`, `can_dispatch_external_reviewer`, `native_shell`, `read_tool`/`shell_tool`/`end_turn_signal`) per harness, plus the tool-name substitution table. Read when a workflow/skill branches on harness identity or a tool name looks Antigravity-specific.
- **Human decision protocol** → `.agent/docs/human-decision-protocol.md` — precedent sweep → web research (`web_search_tool` ladder) → obviousness test → Decision Brief (recommendation first) or autonomous decision logged in the plan's Decision Log and the reflection's Decisions Log. **Read before presenting any question or decision to the human at any workflow stage.**
- **Model & CLI routing** → `.agent/docs/model-routing.md` — the routed stack (3 model tiers — Coordinator/Builder/Router — + external reviewer + isolated-worker mode), the independent-reviewer chain, and nesting/delegation rules. Canonical source for "which model does which task."
- Testing strategy → `.agent/docs/testing-strategy.md`
- Code quality examples → `.agent/docs/code-quality.md`
- **Emerging standards** → `.agent/docs/emerging-standards.md` — living checklist of MCP/GUI/API standards discovered during development. **Read before planning any MCP or GUI MEU.**
- Role specs → `.agent/roles/`
- Handoff template → `.agent/templates/HANDOFF-TEMPLATE.md`
- Current focus → `.agent/context/current-focus.md`
- Known issues → `.agent/context/known-issues.yaml` (SSOT) / `.agent/context/known-issues.md` (generated)
- Full specification → `docs/BUILD_PLAN.md`


<!-- headroom:rtk-instructions -->
# RTK (Rust Token Killer) - Token-Optimized Commands

Prefix shell commands with RTK. Native filters provide compact views only after
command-matrix verification. Unsupported commands and exact evidence use
`rtk proxy`; pass-through-looking forms are not assumed safe. (The originating
repo's `output-evidence-policy.md` is the longer form of this section; it is
deliberately not ported — see MANIFEST §EXCLUDED.)

## Key Commands

> The following fenced block is an argv-only reference block for RTK subcommands.
> It is not executable receipt guidance.

```bash
# Git (59-80% savings)
rtk git status          rtk git diff            rtk git log

# Files & Search (60-75% savings)
rtk ls <path>           rtk read <file>         rtk grep <pattern>
rtk find <pattern>      rtk diff <file>

# Test (90-99% savings) — shows failures only
rtk pytest tests/       rtk cargo test          rtk test <cmd>

# Build & Lint (80-90% savings) — shows errors only
rtk tsc                 rtk lint                rtk cargo build
rtk prettier --check    rtk mypy                rtk ruff check

# Analysis (70-90% savings)
rtk err <cmd>           rtk log <file>          rtk json <file>
rtk summary <cmd>       rtk deps                rtk env

# GitHub (26-87% savings)
rtk gh pr view <n>      rtk gh run list         rtk gh issue list

# Infrastructure (85% savings)
rtk docker ps           rtk kubectl get         rtk docker logs <c>

# Package managers (70-90% savings)
rtk pip list            rtk pnpm install        rtk npm run <script>
```

## Rules
- In command chains, classify each segment and preserve the first failing exit code.
- For debugging, document the bypass reason and retain the P0 receipt.
- `rtk proxy <cmd>` is the canonical unfiltered route for exact evidence.
- On Windows, use PowerShell 7 (`pwsh`) for child scripts that require modern cmdlets
  such as `Get-FileHash`; `powershell.exe` is legacy compatibility only.
<!-- /headroom:rtk-instructions -->

## D6 staged validation registration

Register each adopter check as static, targeted, full or optional runtime, with argv/manual
procedure, cwd, scope (including shared fixtures/config), blocking status, expected result,
native shell and evidence.v1 output. Define input identity for relevant code/tests/config,
environment and external inputs; disable reuse when that identity is unavailable. One
fresh full gate precedes final implementation review. Never present targeted output as full.
The portable record checker is `python tools/durable_evidence.py <artifact>`; final checking
adds `--require-full --expected-state <independently-obtained-state>`. Wrap with the native
receipt/exit pattern in output-evidence-policy. This checks records, not a product suite.
