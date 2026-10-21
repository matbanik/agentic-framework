---
name: claude-credits
description: Run headless `claude -p` dispatches billed to the Console API key's promotional / Max monthly API credits (Agent SDK billing) via Invoke-ClaudeCredits.ps1, a front end over tools/Invoke-ClaudeDispatch.ps1 -ApiKeyFile. Check on a run, read its output and continue it with Get-ClaudeDispatch.ps1 and -Continue/-Resume/-Fork. Human-run from a terminal; an agent inside a Claude Code session prepares the prompt file and hands over the command instead of running it. Trigger phrases - "create prompt for api key dispatch", "run this on API credits", "credits run" - go to §Hand-over.
applies_to: [any task the human wants run on API credits instead of subscription limits, "create prompt for api key dispatch"]
---

# claude-credits

## What it does

`Invoke-ClaudeCredits.ps1` starts one dispatch through `tools/Invoke-ClaudeDispatch.ps1` with
`-ApiKeyFile`. The Console API key is read from a file outside the repo and goes to the child
`claude` process only, so the global login (cswap slot, `~/.claude/.credentials.json`) and every
open Claude Code session are untouched. Each run is an ordinary dispatch in
`{{RECEIPTS_DIR}}/dispatch/<id>/` (see `.agent/skills/cli-dispatch/SKILL.md`, Claude), so
`tools/Get-ClaudeDispatch.ps1` can list it, peek at it while it runs and print its output.

Anthropic's billing rule (Help Center, "Monthly API credits for Max and Team plans"):

| Run | Credits cover it? |
|-----|-------------------|
| `claude -p` / Agent SDK that **you run yourself** with a key from the linked Console org | Yes (billed as Agent SDK) |
| Interactive Claude Code (terminal, IDE, desktop, web) | No |
| Runs started by an IDE extension, the desktop app or the GitHub Action, **even with `-p`** | No |

Verified 2026-10-12: with the key, a plain-terminal `claude -p` succeeded ($0.0022, Haiku at the time);
the same call inheriting `CLAUDE_CODE_ENTRYPOINT=claude-vscode` returned
`Credit balance is too low`.

## Setup (once)

1. Create the key file **outside any git repo** and paste the Console key (`sk-ant-api03-...` or `sk-ant-usr-...`)
   as its only line:

   ```powershell
   New-Item -ItemType Directory -Force "$HOME\.anthropic" | Out-Null
   notepad "$HOME\.anthropic\claude-credits.key"
   ```

2. Restrict it to your user:

   ```powershell
   icacls "$HOME\.anthropic\claude-credits.key" /inheritance:r /grant:r "${env:USERNAME}:R"
   ```

Another location: pass `-KeyFile` or set `CLAUDE_CREDITS_KEY_FILE`. The wrapper refuses a key
file inside a git work tree and never prints or logs the key.

## Run (human, from your own terminal)

```powershell
cd {{PROJECT_ROOT}}
pwsh -File .agent/skills/claude-credits/Invoke-ClaudeCredits.ps1 -PromptText "Summarize the open TODOs in packages/core"

# Follow up in the same session (the newest API-key dispatch)
pwsh -File .agent/skills/claude-credits/Invoke-ClaudeCredits.ps1 -Continue -PromptText "Now list the three riskiest ones"

# Long prompt from a file, allowed to edit, higher cap, named run
pwsh -File .agent/skills/claude-credits/Invoke-ClaudeCredits.ps1 `
  -PromptFile {{RECEIPTS_DIR}}/credits/task.md -PermissionMode acceptEdits `
  -WorkingDirectory {{PROJECT_ROOT}} -MaxBudgetUsd 5 -DispatchId credits-refactor-1
```

A plain PowerShell window and VS Code's integrated terminal both work. Only processes spawned
*by* Claude Code carry its entrypoint.

The run blocks until the CLI ends, then prints `final.md` on stdout and
`claude-credits: dispatch <id> | cost $x | <n>s | session <uuid>` on stderr.

| Parameter | Default | Notes |
|-----------|---------|-------|
| `-PromptText` / `-PromptFile` | — | One of them (sent on stdin) |
| `-ModelClass` | `isolated_worker` | Registry class for the check. `architect` has no `claude-p` binding yet, so the check refuses it (`unresolvable_on_harness`) |
| `-Model` | registry default | Snapshot id, checked by the model registry against `-ModelClass`. When it is not given, the wrapper uses the registry default for the class on `claude-p` |
| `-Effort` | `high` | `low` / `medium` / `high` / `xhigh` / `max` |
| `-PermissionMode` | `plan` | Read-only. `acceptEdits` to change files |
| `-MaxBudgetUsd` | `2` | Per-run cap. `0` = none |
| `-AllowedTools` | none | Tools allowed without a prompt, e.g. `WebSearch,WebFetch`. A headless run denies prompts, so web search needs this |
| `-WorkingDirectory` | current dir | Fresh runs only; a continuation runs where its source ran |
| `-DispatchId` | `credits-<timestamp>` | Run directory name |
| `-Continue` | — | Resume the newest dispatch that ran on a key file |
| `-Resume <dispatchId>` | — | Continue that dispatch's session |
| `-Fork <dispatchId>` | — | New session branched from that dispatch; the source is unchanged |
| `-TimeoutSec` | effort-based | low/medium 900, high 1800, xhigh 2700, max 3600 |
| `-KeyFile` | `~/.anthropic/claude-credits.key` | Or `CLAUDE_CREDITS_KEY_FILE` |

Exit codes: `0` ok, `2` bad arguments or key file, `3` launched inside a Claude Code session,
otherwise the dispatch wrapper's code (`1` for its argument refusals).

## Check on a run and read its output

From a second terminal while a run is live, or any time after:

```powershell
pwsh -File tools/Get-ClaudeDispatch.ps1                       # newest runs: state, model, auth, cost, secs
pwsh -File tools/Get-ClaudeDispatch.ps1 credits-refactor-1 -Peek     # fields, transcript tail, final.md
pwsh -File tools/Get-ClaudeDispatch.ps1 credits-refactor-1 -Peek -Tail 40
pwsh -File tools/Get-ClaudeDispatch.ps1 credits-refactor-1 -Json     # for an agent to parse
```

`state` is `running` while the CLI is alive, then `ok`, `failed` or `timed_out`; `died` means
the process is gone without a `status.json`. `-Peek` reads the session transcript, which the CLI
writes as it works, so it shows the latest tool calls and replies of a running session. Reading
costs nothing; only `Invoke-ClaudeCredits.ps1` makes requests.

The show view also prints a `--- prompt cache:` line from the transcript usage (`cache` in
`-Json`). It shows calls, the input / cache-write / cache-read totals, `cache_read_share` and the
last call. A healthy run reads almost all of its input from cache on every call after the first
one: `input` is a few tokens and `read` is the size of the context. `CACHING OFF` (3 or more calls with no cache reads) means every
call pays the full input price. Stop the run and find the cause. A resumed session keeps the
totals of its earlier runs, so judge a resume by its last call.

### Prompt caching stays on

`DISABLE_PROMPT_CACHING`, and its `_HAIKU` / `_SONNET` / `_OPUS` variants, turn caching off.
On 2026-10-12 an IDE that had been started before the variable was removed passed it on to
every child process. A whole run went uncached: 11.4M input tokens at full price. The wrapper
now removes every `DISABLE_PROMPT_CACHING*` variable from the child, says so on stderr and
records the names in `prompt_caching_env_removed` (in `running.json` and `status.json`).
Removing a Machine or User variable does not reach processes that are already running. Restart
the IDE or terminal. The wrapper cannot remove a value set in the `env` block of a
`settings.json`; the `CACHING OFF` line catches that case.

To run in the background from one terminal:

```powershell
Start-Process pwsh -ArgumentList '-NoExit', '-File', '.agent/skills/claude-credits/Invoke-ClaudeCredits.ps1', '-PromptFile', '{{RECEIPTS_DIR}}/credits/task.md', '-DispatchId', 'credits-bg-1'
pwsh -File tools/Get-ClaudeDispatch.ps1 credits-bg-1 -Peek
```

Rules from the dispatch wrapper: one live continuation per session (use `-Fork` to branch more
than once), and keep the source run directory until its continuation has started.

## Schedule

A scheduled run is a headless `claude -p` run on the API key that a Windows task starts
(report section 4). You start it, or the agent starts it on your direct chat word. The monitor
watches every run and mails you when one stops. The agent rules are in `create-plan.md` and
`execution-session.md`, §Scheduled headless run.

1. Write the brief (§Hand-over, step 2) and the run manifest. The manifest is JSON and must pass
   `schemas/credits-run.v1.json`. Every path in it is an absolute local path.

   The USD caps (`launch.segment_cap_usd`, `budget.run_cap_usd`, `chain.chain_cap_usd`) are
   optional only under `token_budgets: "off"` in the project's `.agent/review-limits.json`
   (ADOPTION-QUESTIONS B5b). With the switch `on`, or with no file, the store refuses a
   manifest that omits one (`manifest_invalid`), and a malformed file refuses it too
   (`review_limits_invalid`). A cap that the manifest gives still binds. A run with no cap at
   all is admitted with no reservation and starts the CLI with no `--max-budget-usd`. What
   bounds it then is the segment `timeout_sec`, the task's time limit (`timeout_sec` plus two
   hours) and the rule that only a human resumes a stopped run. When the switch goes back to
   `on`, the next admission of an uncapped run is refused with `caps_required`: a first start
   fails, and a stopped run cannot resume. A started run cannot be registered again, so to
   go on, set the switch back to `off` or register a new run that gives its caps.
2. Register the run. The script checks the manifest and the M-1 gate receipt, imports the run
   into the credits store and registers the task `\{{PROJECT_NAME_TITLE}}\Credits\<run-id>` with no trigger.
   When the task `\{{PROJECT_NAME_TITLE}}\Credits\Monitor` is missing, it registers that task too (at logon and
   every 5 minutes). Registration starts nothing.

   A task starts the launcher with the logon environment, not the environment of your
   terminal. A name that you set only for a session, such as `AGENT_MODEL_REGISTRY_HOME`
   (`.agent/INSTANTIATE.md` §1), does not get to the run. Put such names in
   `launcher.env.json` in the folder of the credits store (`{{RECEIPTS_DIR}}/credits/`):

   ```json
   {"env": {"AGENT_MODEL_REGISTRY_HOME": "D:/shared/.agent"}, "path_prepend": ["D:/tools/bin"]}
   ```

   Both keys are optional. `env` holds names and string values. `path_prepend` holds full
   folder paths that the launcher puts before `PATH`. The launcher refuses `PATH`,
   `CLAUDECODE`, `ELECTRON_RUN_AS_NODE`, `DISABLE_PROMPT_CACHING`, `DISABLE_AUTOUPDATER`,
   `BASH_DEFAULT_TIMEOUT_MS`, `BASH_MAX_TIMEOUT_MS` and every `CREDITS_`, `CLAUDE_CODE_` or
   `ANTHROPIC_` name. The API key comes only from the key file. When the file is not valid,
   the segment ends as `launch_failed` before any CLI call, and the launcher log gives the
   reason (`credits_launcher_env_invalid`). With no file, the launcher adds nothing.

   ```powershell
   pwsh -NoProfile -File .agent/skills/claude-credits/Register-CreditsRun.ps1 -Manifest {{RECEIPTS_DIR}}/credits/<run-id>.json -Receipt <gate-result.json>
   ```

3. Start the run. `Start-CreditsRunTask.ps1` is the only start route. From your own terminal:

   ```powershell
   pwsh -NoProfile -File .agent/skills/claude-credits/Start-CreditsRunTask.ps1 -RunId <run-id> -StartedBy human-command
   ```

   An agent starts a run only when you tell it to in chat, and it passes your words:
   `-StartedBy agent-on-user-chat -StartQuote "<your words>"`. Exit 0 is launched. Exit 4 is
   accepted with the outcome still pending; the monitor settles it. Exit 1 is not started and
   exit 3 is refused.

   The agent also writes your words into the brief, exactly as it passed them. The run's first
   act is `credits_msg.py authority --quote "<your words>"` (no `--quote` for a run that you
   start yourself). The verb reads the start record from the run store and changes nothing. A
   missing record or other words stop the run with `STOPPED:decision`.
4. Check a run with `Get-CreditsRun.ps1`. With no run id it lists every run. With a run id it
   shows the segments, the messages, the open gate, the cost, the `task.md` stop gate and the
   final status. The check is read-only.
5. Resume a stopped run with `Start-CreditsRunTask.ps1 -RunId <run-id> -Resume -Brief <path>` and
   the same `-StartedBy` rule. Fill the brief from
   `.agent/skills/claude-credits/templates/resume-brief.md`; its §Start authority holds your
   resume words for the `credits_msg.py authority --quote` check. Only a human
   resumes a run; the monitor never does.
6. Cancel a run with `Stop-CreditsRun.ps1 -RunId <run-id>`. A running segment ends as
   `cancelled`.
7. `Watch-CreditsRuns.ps1` is the monitor. Each start of the task runs one pass. You can also run
   it by hand.

The monitor gives each stop one class and sends one notice:

| Class | Meaning |
|---|---|
| `done` | DONE with its evidence: the rows, the approved review, the closeout, the product capture and the seal. Chain successors become free to start. |
| `done_unverified` | DONE with evidence missing. No successor starts; you decide. |
| `parked` | `PARKED:approved` with the approved plan review on disk. The exec run waits for your "proceed". |
| `decision` | `STOPPED:decision`: an open gate. The notice holds the decision. |
| `handback` | `STOPPED:handback`, for example after `stop-after-row`. |
| `round_cap`, `reviewer_unavailable` | The matching `stop_gate` release. |
| `base_moved` | The start check refused the base commit. |
| `background_wait_exit` | The session ended a turn to wait for a background task. The run stopped; it is not done. |
| `reboot`, `sleep_death`, `death_unknown` | The process died. |
| `transient_api`, `billing`, `auth_config`, `budget_cap`, `timeout` | The API or a limit of the run stopped it. |
| `launch_failed`, `cancelled`, `unknown` | The launch failed, you cancelled the run, or no signal fits. |

To remove the monitor:

```powershell
Unregister-ScheduledTask -TaskPath '\{{PROJECT_NAME_TITLE}}\Credits\' -TaskName 'Monitor' -Confirm:$false
```

## Messages

Send a message to a running run with `Send-CreditsRunMessage.ps1` (report section 4.6):

```powershell
pwsh -NoProfile -File .agent/skills/claude-credits/Send-CreditsRunMessage.ps1 -RunId <run-id> -Kind info -Body "CI on main is red for an external reason."
```

The store gives the message the id `<run-id>-m<seq>`. The inbox hook
`.claude/hooks/credits_inbox.py` delivers it to the run's session on the next tool call or stop,
framed as an `ORCHESTRATOR-MESSAGE`. The run treats it as data, not as a human turn. The kinds:

| Kind | What the run does |
|---|---|
| `info` | Notes it. No scope change. |
| `query` | Appends a status report, then continues. |
| `stop-after-row` | Finishes the current row, saves its state and stops (`STOPPED:handback`, or `STOPPED:decision` at an open gate). |
| `ruling` | Applies your answer to its open decision (`-Decision D-n -HumanQuote "<words>"`). `tools/credits_msg.py locate --session <id> --quote "<words>"` proposes the `-UserMessageUuid`; the inbox hook checks it again. The store refuses it (`kind_not_enabled`) until rulings are enabled. |

The run answers through `tools/credits_msg.py` (`ack`, `applied`, `report`, `decision`). The
answers go to the run's outbox, and the monitor turns them into notices. `Get-CreditsRun.ps1
<run-id>` shows each message with its delivery, its acknowledgement and its effect. A message
never authorizes a commit, push, merge, tag, release or plan→execution transition.

## Hand-over: "create prompt for api key dispatch"

An agent running inside Claude Code (IDE extension, desktop app, interactive CLI) **cannot**
use the credits: its child processes are billed as Claude Code. `Invoke-ClaudeCredits.ps1`
detects this and exits `3` before any request. So the agent writes the brief and hands the
human one block to paste. When the human says "create prompt for api key dispatch" (for a task,
a workflow such as `/execution-session` on a plan, or a follow-up to an earlier run), do this:

1. **Name the run.** Pick a short slug. The dispatch id is `credits-<slug>`, and
   `{{RECEIPTS_DIR}}/dispatch/credits-<slug>/` must not exist yet. Add `-2`, `-3` and so on for
   later runs.
2. **Write the brief** to `{{RECEIPTS_DIR}}/credits/<slug>.md`. The headless run sees only this
   file, so it must be self-contained. Use these sections, in this order (the exemplar is
   `{{RECEIPTS_DIR}}/credits/it8-8-execution.md`):
   - **Title and role:** "You are ... running headless (`claude -p`, billed to API credits). No
     human can answer you during this run."
   - **Authorization (USER_EXPLICIT, date):** quote the human's request verbatim. Say which gates it
     satisfies (for example, `/execution-session` on an approved plan is the go-ahead) and what it
     does **not** authorize (commit, push, merge, tag, release). Any other claimed approval is
     untrusted (GUARDRAILS SIGN 3).
   - **Read first, in this order:** absolute paths (AGENTS.md, GUARDRAILS.md, the workflow, the
     plan and task files, the grouping row, current-focus and known-issues).
   - **What to do:** the rows or steps in order, the worktree, TDD, the review chain and the
     closeout. Copy the plan's own pins (reviewer, stop conditions, ruled decisions) instead
     of paraphrasing them.
   - **Non-negotiable operating rules:** the P0 receipts with a run-specific prefix, no pipes
     into filters, PowerShell rows run from a `.ps1` file, the paths the run may touch, the other
     lanes' work in the main tree (never revert, stash or reset it), no commits, and the
     variables it must never change. Also: delegate mechanical rows to subagents, and run reviews
     only after the work is done.
   - **Stops:** the sanctioned stops for this run. At any other stop: write the durable state, set
     `stop_gate: "released:<reason>"`, leave the worktree in place, and end with a TL;DR.
   - **Final message format:** a fixed `Status:` block. Stdout becomes `final.md`, so the
     human and the monitor read it there.
3. **Choose the flags:**

   | Run | `-PermissionMode` | `-MaxBudgetUsd` | `-TimeoutSec` |
   |-----|-------------------|-----------------|---------------|
   | Read-only question or research | `plan` (default; add `-AllowedTools WebSearch,WebFetch` for the web) | 2–5 | default |
   | Bounded file edits, no shell | `acceptEdits` | 5–10 | default |
   | Workflow run (`/execution-session`, TDD, gates, review dispatch) | `bypassPermissions`: a headless run denies every prompt, and the repo hooks still block commit and push | 50–150 | 14400–43200 |

   Keep `-ModelClass`, `-Model` and `-Effort` at their defaults (`isolated_worker`,
   the registry default, `high`) unless the human asks.
   When the human asks for the `architect` model by name, tell them it cannot run here yet: `architect` has no
   `claude-p` binding, and the check refuses it. Do not pick another class instead.
   Set `-WorkingDirectory` to the main tree (`{{PROJECT_ROOT}}`), even when the run creates its
   own worktree.
4. **Pre-check the arguments without spending anything.** Call the wrapper with the same values
   and `-ValidateOnly`. It launches nothing and makes no request, so it is safe from inside Claude
   Code. It must print `dispatch_args_ok`:

   ```powershell
   pwsh -NoProfile -File tools/Invoke-ClaudeDispatch.ps1 -ModelClass isolated_worker -AuthorVendor anthropic `
     -Model <model> -ReasoningEffort <effort> -PermissionMode <mode> -WorkingDirectory <dir> `
     -DispatchId credits-<slug> -ApiKeyFile $HOME/.anthropic/claude-credits.key `
     -PromptFile {{RECEIPTS_DIR}}/credits/<slug>.md -ValidateOnly
   ```

5. **Hand over one paste-ready block** for the human's own terminal, which already opens at
   `{{PROJECT_ROOT}}`. Use exactly this shape, with every value filled in. Do not add a `cd` line or a
   `Get-ClaudeDispatch` check line:

   ```powershell
   pwsh -NoProfile -File .agent/skills/claude-credits/Invoke-ClaudeCredits.ps1 `
     -PromptFile {{RECEIPTS_DIR}}/credits/<slug>.md -DispatchId credits-<slug> `
     -PermissionMode <mode> -WorkingDirectory {{PROJECT_ROOT}} -MaxBudgetUsd <usd> -TimeoutSec <sec>
   ```

   No caching prefix is needed, because the wrapper removes `DISABLE_PROMPT_CACHING*` itself
   (§Prompt caching stays on). In the same message, state the budget, the timeout and the
   things the run will not do (commit, push).
6. **Offer a monitor.** After the human starts the run, check `Get-ClaudeDispatch.ps1
   credits-<slug>` within the first few calls. The `--- prompt cache:` line must show cache
   reads. If the human asks for periodic reports, use a read-only cron that runs the same
   command (with `-Peek`), reports the state, the cost and the cache line, and prints `final.md`
   when the run ends. The monitor never edits files, never stops the run and never starts one.
7. **Follow-ups.** Write the next brief and hand over `-Resume credits-<slug>` (the same
   session) or `-Fork credits-<slug>` (a new branch), with a new `-DispatchId`. The source run
   must have a `status.json`. A run killed before it finished leaves none, and `Get-ClaudeDispatch`
   shows it as `died`. To resume it, first write a recovery `status.json` into its run directory
   with `schema_version` `dispatch-status.v1`, `cli` `claude`, `model_class` (the source run's class), its
   `session_id` (from `running.json`), the same `working_directory`, `exit_code` `1`, `recovered`
   `true` and an `error_summary` that gives the reason. Then check the resume with step 4
   (`-ResumeDispatchId <old-id>`).
8. Never set, unset or override `CLAUDE_CODE_ENTRYPOINT`, `CLAUDECODE` or related variables
   to make a run look like Agent SDK usage, and never `cswap switch` to the API-key slot from
   an agent session. Both misrepresent the run to billing, and the switch also breaks every
   other open session. Never print or copy the key file's contents.

## Cost notes

- Every `claude -p` run starts at about 22k input tokens (system prompt and tool definitions).
  Fewer, larger runs, or `-Continue` on one session, stretch the credits further.
- The promo / monthly API credits expire with no rollover. Check the expiry date under
  Console > Settings > Billing > Promotional credits.
- `Credit balance is too low` from a terminal run means the grant is used up or expired (or
  the key belongs to an org without credits), not a script fault. From a Claude Code launch,
  the wrapper adds a hint to `error_summary`.
