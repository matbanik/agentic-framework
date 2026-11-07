# Remote hosts: send planning, execution and test jobs to another machine

Status: proposal, 2026-11-01. Nothing is installed or committed. This replaces
`2026-10-31-fleet-nodes.md`.

Decisions needed: D-1 and D-2 in section 8.

## 1. The design in brief

The orchestrator (<hub host>) reaches a remote host (<member host> is the first) over `ssh` and `git`. The
existing dispatch, credits and messaging tools run on the host as they do today. There is one new
tool, `tools/remote.py`, and it has four commands:

| Command | What it does | New logic |
|---|---|---|
| `remote test <host> -- <command>` | Runs tests on the host against this session's files, including uncommitted ones | Snapshot, push, wait, copy results back |
| `remote run <host> --kind plan\|exec --auth credits\|subscription --brief <file>` | Starts `claude -p` on the host in its own worktree | Prepare a worktree, then call the existing credits scripts |
| `remote call <host> <existing script> <args>` | Runs an existing check-in script on the host | None: it passes the call through ssh |
| `remote land <host> <job>` | Brings a finished job onto <hub host>'s `main` | Fetch, merge check, commit |

The host needs no daemon, queue or shared database. Nothing on the host can push to GitHub.

## 2. Sending plan and execution jobs

### What happens

1. You tell a <hub host> session to run something on <member host>, for example "run the S42 execution on
   <member host> on credits". The session writes the brief as usual.
2. `remote run` pushes `main` to the host and copies the brief over with `scp`.
3. On the host it picks a free worktree slot (section 4) and installs dependencies only if a
   lockfile changed.
4. It writes the run manifest using the host's own paths, then calls the existing
   `Register-CreditsRun.ps1` and `Start-CreditsRunTask.ps1`. Your words travel as `-StartQuote`.
5. The existing launcher starts `claude -p` with the brief on stdin, inside a Task Scheduler task.
   The run's first act is the existing `credits_msg.py authority --quote` check.
6. `remote run` prints the run id and returns. <hub host> can be switched off while the run works.

Arguments go to the host as a JSON file, not on a command line, so PowerShell, bash and zsh
quoting never matters.

**You don't need to open a session on the host.** The earlier proposal required that, but it came
from my own reading of the authority rule. `Start-CreditsRunTask.ps1` already accepts an agent
start with your quote when `credits_start_policy` allows it (D-1).

### With or without credits

| `--auth` | Key handling | Bills to |
|---|---|---|
| `credits` | Today's path: key file on the host, passed to the child process only | The Console org's API credits |
| `subscription` | No key: the child uses the host's Claude login, recorded as `auth_mode: inherited` | The subscription's limits |

Anthropic's help page, updated 2026-10-07, confirms both routes. `claude -p` on a plan login still
draws from subscription limits. On a linked Console key, the monthly API credits can cover it.

The only change needed is a `launch.auth` field in the run manifest. `Invoke-ClaudeDispatch.ps1`
already handles a missing key, but `Start-CreditsRun.ps1:591` always passes `-KeyFile` and
`Invoke-ClaudeCredits.ps1:240-252` always requires one. Both skip the key when `auth` is
`subscription`. USD caps don't apply to a subscription run, so its timeout bounds it.

Subscription runs use the same launcher so they get the same messaging and monitor.

### Choosing the host at planning time

A plan's frontmatter gets one optional line, `host: <member host>`, and the plan states why in a sentence.
`remote run` uses that value unless told otherwise. There's no label matcher: with one or two
hosts, the planner can decide this itself.

## 3. Checking in on a session

This uses the existing messaging with no new transport or format. Each row is an ssh call to a
script that already exists:

| You want | Command | Existing tool on the host |
|---|---|---|
| List runs | `remote call <member host> Get-CreditsRun` | `Get-CreditsRun.ps1` |
| One run's state, cost, messages, open gate | `remote call <member host> Get-CreditsRun <run>` | Same |
| See what it's doing right now | `remote call <member host> Get-ClaudeDispatch <dispatch> -Peek` | `Get-ClaudeDispatch.ps1` |
| Ask for a status report | `remote call <member host> Send-CreditsRunMessage -RunId <run> -Kind query -Body "..."` | Delivered by `credits_inbox.py`; the run answers with `credits_msg.py report` |
| Tell it something | Same, `-Kind info` | Same |
| Stop after the current row | Same, `-Kind stop-after-row` | Same |
| Cancel | `remote call <member host> Stop-CreditsRun -RunId <run>` | `Stop-CreditsRun.ps1` |

The host's monitor (`Watch-CreditsRuns.ps1`) classifies each stop and sends mail, as it does today.

Three limits apply:

- **A message waits for the next tool call.** A run inside a long gate won't see it until the gate
  ends. `-Peek` still works in the meantime.
- **Rulings don't work across machines.** The inbox hook checks a `ruling` against the orchestrator
  session's transcript, and that file is on <hub host>. Remote runs set `ruling_enabled: false`. A run
  that needs a decision ends with `STOPPED:decision`; you answer, and it resumes with a brief, as a
  human-started resume already does.
- **Reading needs the host to be reachable.** The run continues if it isn't.

## 4. How git works

### The rules

1. **There is one `main`, on <hub host>.** Only <hub host> commits to it and only <hub host> pushes it to GitHub.
2. **The host's `main` is a read-only copy.** It moves only when <hub host> pushes to it.
3. **Agents on a host never touch `main`.** Each works in its own worktree. Its `main`-based
   history looks normal, and its brief says not to commit, branch or push.
4. **Work comes back as one squashed, signed commit** that <hub host> makes.
5. **Sessions on <hub host> change nothing.** av-kit sessions keep working on `main` in `P:/av-kit`, and
   Zorivest sessions keep using their lanes.

### What's on each machine

```
GitHub main
   ^  git push origin main           <hub host> only, on your approval
   |
<hub host>  P:/av-kit  main               signed commits; no branches added, no worktrees added
   |  ^
   |  |  git fetch <member host> refs/heads/lane/<slug>     then squash onto main
   |  |
   v  |  git push <member host> main         <hub host> to host, fast-forward only
<member host>  <root>/av-kit  main           read-only copy; no origin, no GitHub or signing credentials
   |
   |  worktrees share this repo
   +-- <root>/slots/av-kit/test      detached HEAD; test jobs only
   +-- <root>/slots/av-kit/1         branch lane/<slug>; one plan or exec job
```

`<root>` is any folder set per host. Nothing depends on a drive letter.

### Host setup, once per project

```
# On the host: an empty repo, so it never needs to reach <hub host> or GitHub
git init -b main <root>/av-kit
git config receive.denyCurrentBranch updateInstead    # the checkout follows <hub host>'s pushes
git config receive.denyNonFastForwards true

# On <hub host>: first copy
git remote add <member host> <member host>:<root>/av-kit
git config --unset remote.<member host>.fetch
git push <member host> main

# On the host: slots
git worktree add --detach <root>/slots/av-kit/test main
git worktree add --detach <root>/slots/av-kit/1 main
```

Then install dependencies in each slot. The slots stay in place between jobs, like CI runner
workspaces. Each keeps its own `.venv` and `node_modules`, so no links are needed. They reinstall
only when a lockfile hash changes.

On <hub host>, the `<member host>` remote has no fetch refspec, so a fetch never creates a ref here.

### One execution job

| Step | Where | Command | Result |
|---|---|---|---|
| 1. Send | <hub host> | `git push <member host> main` | Host's `main` now equals <hub host>'s |
| 2. Claim a slot | Host | `mkdir <slot>.lock` | Atomic on every OS. If it fails, the slot is busy |
| 3. Check out | Host | `git -C <slot> switch -c lane/<slug> main`, then `git clean -fd` | Clean worktree at <hub host>'s commit |
| 4. Work | Host | `claude -p`, through H1, review and H2 | Files change in the slot only. Zorivest's `lanes.py claim` works unchanged here because HEAD is on `lane/<slug>` |
| 5. Save | Host, after `claude` exits | `git add -A`, then an unsigned `git commit -F <run's commit message>` | One commit on the host-only branch |
| 6. Report | Host | The monitor mails the stop class | You know it's ready |
| 7. Land | <hub host>, on your word | `remote land <member host> <job>` | See below |
| 8. Tidy | Host | `git -C <slot> switch --detach main`, `git branch -D lane/<slug>`, `git clean -fd`, remove the lock | Slot is free. Ignored `.venv` and `node_modules` stay. Git won't delete a branch a slot still has checked out, so the switch comes first |

A slot stays held until its job is landed or dropped (`remote land --drop`), so unfinished work
can't be overwritten. A host's slot count therefore limits how much work can wait to land.

### Who closes out a session

The remote agent does the whole closeout up to the commit: H1, the independent review on the host
through Codex, H2 and the commit message. It then stops. It doesn't land, sign or push.

Landing is a commit, so the existing rule applies: it needs your word or an authorized plan step.
Any <hub host> session can run it. This closes the gap in the earlier proposal, which never said who
finished a job.

### Landing on av-kit

```
git fetch <member host> refs/heads/lane/<slug>
git merge-tree --write-tree --merge-base=<job base> main FETCH_HEAD   # checks without touching files
git merge --squash FETCH_HEAD
git commit -F <run's commit message>                                  # normal hooks, normal signing
git push <member host> main                                                   # host's copy catches up
```

| Case | What happens |
|---|---|
| `main` hasn't moved since the job's base | The tree is identical, so the host's gate and review still apply. Commit. |
| `main` moved, merge is clean | `remote land` runs the gate on the merged tree through `remote test`, and commits only if it passes |
| `merge-tree` reports a conflict | Stops with nothing changed. You resolve it, or send a new job based on current `main` |
| Another session has uncommitted edits to a file in the job | `git merge --squash` refuses and changes nothing. Land after that session commits |
| Another session has uncommitted edits elsewhere | Left alone and not included in the commit |

Pushing to GitHub stays a separate step, approved as it is today.

### Landing on Zorivest

Zorivest keeps its own pipeline. The difference is that the work arrives from the host:

```
git fetch <member host> refs/heads/lane/<slug>
git worktree add -b lane/<slug> P:/zorivest-wt/<slug> FETCH_HEAD
```

From there it's an ordinary lane: `lanes.py claim`, `land`, the journal, and `commit_batch.py`
writing signed `main`. A <hub host> session runs H2-3c to H2-6, the closeout rows that land the work
and finalize the task files. `claim` may need a `--from <commit>` flag, because it has to record a
base that was created elsewhere. This is the only Zorivest tool change I expect.

### Tested

I ran the av-kit flow in a throwaway repo on 2026-11-01 with git 2.56:

- The host's checkout followed pushes, and a dirty checkout refused one: `Working directory has
  unstaged changes`.
- Landing kept another session's unrelated edits and untracked file out of the commit.
- `merge-tree` returned exit 1 on a real conflict and changed nothing.
- `merge --squash` refused when local edits overlapped the job.
- The commit's tree was identical to the one `merge-tree` predicted.
- The first push into an empty host repo checked out `main`.
- <hub host> could push `main` while a slot held a job on its lane branch, and the job's files stayed
  untouched.
- After a slot was tidied, its ignored `.venv` remained and the job's files were gone.
- A test slot left dirty reached the next snapshot with a tree identical to <hub host>'s.

The test also corrected some of my assumptions. Pushing to `refs/heads/...` or fetching with the
default refspec creates a tracking ref on <hub host>, so the test snapshot goes to a non-branch ref and
the remote has no fetch refspec. A plain `git clone` from <hub host>, a branch delete inside its own
slot, and a plain `switch --detach` in a dirty test slot would each have failed, so the commands
above avoid them.

All of this ran between local folders on <hub host>. Nothing has crossed ssh to <member host> yet, and the
PowerShell default shell on the far end is untested until phase 0.

## 5. Running only tests on a host

An open session on <hub host> keeps working here and sends just the test command to the host. This is
for rows like H1-2, when the changes usually aren't committed yet.

```
python tools/remote.py test <member host> -- uv run pytest tests/ -x --tb=short -q
python tools/remote.py test <member host> --steps <file with one command per line>
python tools/remote.py test <member host> --paths <my files> -- <command>
```

| Step | Where | Command |
|---|---|---|
| 1. Snapshot | <hub host> | Temporary index: `git add -A`, `git write-tree`, `git commit-tree -p HEAD`. The real index, branch and files don't change |
| 2. Send | <hub host> | `git push <member host> <sha>:refs/remote-test/<id>`. Only changed objects travel |
| 3. Check out | Host | `git -C <root>/slots/<project>/test switch --discard-changes --detach <sha>`, then `git clean -fd`. `--discard-changes` is needed because a test that edits a tracked file would otherwise block the next checkout. Reinstall only if a lockfile changed |
| 4. Run | Host | One-shot scheduled task, with output to a log file |
| 5. Wait | <hub host> | Polls `status.json` over ssh. If the network drops, the test continues; `remote test --attach <id>` picks it up again |
| 6. Return | <hub host> | Copies the log and results to `C:/Temp/<project>/remote/<id>/`, deletes the host ref, and exits with the test's own exit code |

The last output line is JSON with `host`, `commit`, `tree`, `exit_code` and the receipt path.
Handoff evidence cites these, and the `tree` shows exactly what was tested.

The session runs this with `run_in_background`, as it would a local gate, and is woken when it
finishes. This is the "like a subagent" behaviour you first asked for.

The snapshot uses a temporary index because `git stash create`, the usual trick, leaves out
untracked files. In the test it missed one, and this tree has new untracked files right now. By
default the snapshot holds the whole working tree, the same files a local gate sees. `--paths`
tests only your files on top of `HEAD`, for when another session's unfinished work would break the
run.

**Why a scheduled task.** Windows OpenSSH ends every process from an ssh session when it closes,
and the maintainers mark this "by design". The Interactive task also gives Electron E2E a real
desktop. The task's runner clears `ELECTRON_RUN_AS_NODE`, which breaks Electron launches when set.

### Which closeout rows go remote

| Row | Where | Why |
|---|---|---|
| av-kit H1-2, the D6 registered checks | Host | Heavy, and the main reason for this feature |
| av-kit H1-6b, full evidence rerun when stale | Host when it reruns the gate; the evidence check stays local | Same |
| Zorivest H1-2, `validate_codebase.py` full gate | Host (D-2) | Same |
| Zorivest H1-2a, `--tree-delta` | <hub host>, against the returned run folder | It must compare against the live tree |
| H1-1, H1-6a, H2-2 to H2-5 validators | <hub host> | They only read the session's task, handoff and reflection files |

**Zorivest's identity check should carry across.** `inputs.manifest` holds paths and blob ids, and
`.gitattributes` makes line endings the same everywhere, so `--tree-delta` on <hub host> should prove
the host tested the tree under review. I haven't run this across two machines, so it's the first
thing phase 2 checks. A difference in ignored dependency files is the likely failure.

## 6. Linux and macOS

No machine needs a `P:` drive. Each host's paths live in one file on <hub host>:

```yaml
# <registry home>/remote-hosts.yaml
<member host>:
  ssh: <member host>            # alias from ~/.ssh/config
  root: C:/agents       # /home/<user>/agents or /Users/<user>/agents elsewhere
  registry: C:/agents/.agent
  model_jobs: 1
  test_jobs: 1
```

`ssh`, `git`, Python and `pwsh` all exist on the three systems, and `remote.py` is standard-library
Python. These are the Windows-specific parts:

| Hardcoded or Windows-only today | Fix | Needed for |
|---|---|---|
| `P:/av-kit`, `P:/zorivest` in tools | `git rev-parse --show-toplevel` | Every host. 6 tracked av-kit files in `.claude/agents`, `tools`, `tests` and `ui/tests`; 13 Zorivest files in `tools/`. `P:` appears elsewhere in both repos, and the first gate on the host will show whether any of it matters |
| `P:/.agent` | `AGENT_MODEL_REGISTRY_HOME`, which exists but isn't honoured everywhere | Every host |
| `P:/zorivest-wt` in `executor_worktree.py` | Nothing: hosts use slots | None |
| `C:/Temp/<project>` receipts in rules and task rows | A `RECEIPTS_DIR` variable with a temp-dir default, as `ZORIVEST_GATE_RUNS_DIR` already does | Linux, macOS |
| Task Scheduler | `New-CreditsSchedulerAdapter` is already a swappable adapter. Add `systemd-run --user` and launchd versions | Linux, macOS |
| Win32 job objects in `CreditsRun.psm1` | A process group | Linux, macOS |
| Starting a detached test | One function per OS: scheduled task, `systemd-run --user`, `launchctl` | Linux, macOS |

So Windows hosts come first, and <member host> doesn't get a `P:` drive. If a gate fails there because of
a hardcoded path, that path gets fixed. The Linux and macOS rows are built when such a host exists.
Until then, `remote test` is the first part to port, since it needs only the last row.

## 7. Prerequisites and rollout

### On each host

Versions are <hub host>'s, from the 2026-10-31 inventory.

| Group | Items |
|---|---|
| Access | OpenSSH Server, key-only, firewall rule scoped to <hub host>; a logged-in console session for Interactive tasks. A reboot needs a console logon, because <member host>'s `AutoAdminLogon` is 0 |
| Toolchain | git 2.56 (`core.autocrlf=true`, `commit.gpgsign=false`), PowerShell 7.6.9, Node 24.19.0, npm 11.6.2, uv 0.12.5, Python 3.12.12 and 3.14.7, rtk 0.42.2, ripgrep, fd, jq, .NET SDK 8 and ffmpeg for av-kit, Go only for Zorivest TUI work |
| Agent CLIs | `claude` 2.1.312, `codex` 0.165.0, `cswap` 0.29.0, `ccswap` 0.42.1 |
| Files | Both project clones, the `.agent` registry, `~/.claude/CLAUDE.md`, `RTK.md`, and `settings.json` after review |
| MCP | serena and sequential-thinking; avkit for av-kit |
| Set up by you at the console, never copied | Claude login in `cswap`; Codex login; a new Console key for this host at `~/.anthropic/claude-credits.key`, so it can be revoked alone; the mail password through `agent_notify.py setup`; the credits gate receipt from `probes/run_gate.py` |
| Never on a host | `gh`, GitHub credentials, `origin`, the signing key |

Test jobs need only the first two groups plus the clones. Model jobs need the rest.

### Rule changes

| Rule | Change |
|---|---|
| av-kit `AGENTS.md:102`, "No branches or worktrees" | Add: this applies on <hub host> and GitHub. On a remote host, only `remote.py` creates slot worktrees and `lane/<slug>` branches, and they never leave the host. Agents still create neither. Re-pin the rule-map hash |
| Zorivest task template H1-2 (D-2) | Allow a host's checkout of the exact tree, proven by `--tree-delta` |
| `claude-credits/SKILL.md` | Add the remote start route and `launch.auth` |

### Phases

Each phase is useful on its own, and you can stop after any of them.

| Phase | Work | Done when |
|---|---|---|
| 0 | Set up <member host>: access, toolchain, clones, slots | One `uv run` and one `npm` command run in a slot over ssh |
| 1 | `remote test`, on av-kit | A live <hub host> session runs the D6 checks on its uncommitted tree on <member host>, including E2E, and gets the right exit code and receipts back |
| 2 | `remote test`, on Zorivest | A full gate on <member host> passes `--tree-delta` on <hub host> |
| 3 | `remote run` and `remote call`, on Zorivest | A plan job and an exec job run on both auth modes, and a `query` message gets a report back. The first credits run is small, and its cost is checked in the Console |
| 4 | `remote land` | One av-kit job and one Zorivest job land, with `main` both moved and unmoved |
| 5 | Model jobs for av-kit | av-kit adopts `claude-credits`, `Invoke-ClaudeDispatch` and the inbox hook from the framework. It has none of them today |
| Later | Linux or macOS | The first such host exists |

### Known risks

- **<member host> is modest:** 2 cores, 4 threads, on Wi-Fi. Gates may take longer than on <hub host>. They do
  free <hub host>, but this design doesn't speed up a test run.
- **E2E opens windows on <member host>'s desktop,** the one you work at. Run those when you aren't using
  it, or keep E2E local.
- **One model job and one test job can overlap.** Zorivest's gate probe already reports a gate
  in another tree on the host (`quiet_busy:host:<pid>`). av-kit has no such probe, so its runs just slow down.
- **Squashing leaves one commit per job.** The host's branch is deleted after landing.
- **Credits billing depends on a clean launch environment.** ssh doesn't carry
  `CLAUDE_CODE_ENTRYPOINT`, and the launcher refuses a nested start, so no variable gets overridden.
  This is the same route as an agent-started scheduled run today. Phase 3 confirms it with a small
  run before anything large.

## 8. Decisions for you

**D-1: May a <hub host> session start a job on a host on your chat word?**
`credits_start_policy` defaults to `human-only`. Under that value `remote run` can't start
anything, and you'd run the start command yourself. **I recommend `agent-on-user-chat` in the
hosts' credits config.** Your quote is recorded and checked by the run, and only you can resume a
stopped run.

**D-2: Can a Zorivest gate on a host count as H1-2 evidence?**
H1-2 says to run on "the tree the review will see" and never in a snapshot worktree. Remote gates
break that wording, though the rule targets the `--snapshot` mode, which is a different mechanism.
**I recommend allowing it when `--tree-delta` on <hub host> passes.** If you decline, Zorivest's H1-2
stays local, and remote tests are for targeted runs only. av-kit is unaffected.

## 9. What was removed from the earlier proposal

| Earlier proposal | Now |
|---|---|
| 10 verbs | 4 commands |
| You open a session on the node to start model jobs | The orchestrator starts them on your word |
| `P:` required on every node | Per-host paths, no drive requirement |
| Reservation and slot-weight files, finalization barrier, index commit, restore | A worktree slot and one `mkdir` lock |
| `refs/jobs/<id>/in\|out`, result files, ID verification | Push `main`, fetch one branch |
| Label matcher and placement block | One `host:` line in the plan |
| Memory sync | None: the brief is self-contained |
| `doctor` | Phase 0 checklist; the first test job shows what's missing |
| Whole-tree landing rules | `merge-tree`, then `merge --squash` |
| Who runs collect and land: unspecified | Any <hub host> session, on your word |

The earlier proposal passed three rounds of peer review against criteria I wrote, and each fix
added machinery. This one hasn't been peer reviewed.

## 10. Sources

- [Use the Claude Agent SDK with your plan](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan), Anthropic Help Center: billing for `claude -p`.
- [git-worktree](https://git-scm.com/docs/git-worktree): detached throwaway worktrees for testing; refs shared across worktrees.
- [git-sarah](https://rtime.ciirc.cvut.cz/~sojka/blog/git-sarah): a script that pushes `git stash create` over ssh and runs a command on the remote. The search summary described it; the page itself wasn't read. The test snapshot here follows the same idea and also captures untracked files.
- [Win32-OpenSSH #1195](https://github.com/PowerShell/Win32-OpenSSH/issues/1195): processes end with the ssh session, by design; Windows has no `nohup` or `tmux`.
- [Parallel `claude -p` in worktrees](https://dev.to/stacknotice/git-worktrees-claude-code-run-parallel-ai-agents-on-the-same-repo-2026-mga), a community pattern: one worktree per headless run. I found no official Anthropic guide for running `claude -p` over ssh.
