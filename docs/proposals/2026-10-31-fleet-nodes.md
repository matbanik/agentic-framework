# Fleet nodes: delegating plans to independent machines

Status: superseded on 2026-11-01 by [2026-11-01-remote-hosts.md](2026-11-01-remote-hosts.md),
because the design was too complex and worked only on Windows. Don't implement it. Its prerequisite
inventory in section 4 is still accurate as of 2026-10-31.

## 1. The design in brief

A node is a machine that can already run everything <hub host> runs. To delegate, <hub host> hands it a
commit and a brief, the node runs the existing dispatch stack, and the result comes back as a
commit plus a result file.

```
job = (project, commit, brief, node)  ->  (commit, result.json)
```

- **No new service.** There is no daemon, queue, database or mesh. The tools are `ssh`, `git`
  and Windows Task Scheduler, which the credits runs already use.
- **Placement is a plan field.** The plan records what the work needs. A small matcher picks the
  node and writes the choice and reason into the plan, so the human sees it when approving the plan.
- **Nodes are independent.** A node keeps its own run store, receipts, logins, monitor and mail.
  Once a job has started, <hub host> can be switched off.
- **<hub host> is the only publisher.** Nodes have no `origin`, no GitHub credentials and no signing
  key. Job commits carry work to <hub host>, and <hub host> writes the `main` commits through the existing
  land route.

The new code is:

- one tool with eight verbs (`doctor`, `place`, `send`, `status`, `collect`, `sync`, `attach`,
  `snapshot`), plus two that only a human runs (`release`, `restore`)
- a node-side launcher
- one node list and one plan block
- three additions to Zorivest's `lanes.py`

### Acceptance criteria

These come from the human's request. The design is judged against them.

- **AC-1:** With the section 4 prerequisites installed, a node can run `gate`, `plan` and `exec`
  work for both `P:/av-kit` and `P:/zorivest`, and `fleet doctor` can check every prerequisite.
- **AC-2:** Only <hub host> pushes to GitHub. Nodes use local git only and hold no GitHub credential,
  `origin` or signing key.
- **AC-3:** There are no PRs and no branches on `origin`. Work returns as git commits and lands on
  `main` through the existing land route.
- **AC-4:** Planning decides where a plan runs. The plan records the node and the reason, and
  execution either honours that or stops.
- **AC-5:** Nodes don't depend on <hub host>. A job that has started finishes and reports even if
  <hub host> is off.
- **AC-6:** The design extends the existing CLI dispatch and credits protocols instead of
  replacing them. It keeps their rules on start authority, billing context and human-only
  resume.
- **AC-7:** There is no new long-running service. Adding a node takes only the install script
  and one row in the node list.
- **AC-8:** No secret or credential is copied between machines or committed to git.
- **AC-9:** Every decision that needs the human is presented in the human decision protocol format,
  with a recommendation and a default for when he doesn't answer.
- **AC-10:** Claims about the repo evidence, vendor behaviour and the inspiration projects are
  accurate and sourced.

## 2. What the evidence says this will and won't fix

I read about 40 of the 438 Zorivest reflections in full or in part and searched the rest by
keyword, along with the Zorivest memories.

**It fixes load contention between sessions.**

- "Separate executor worktrees isolate files but not machine memory": three concurrent gates
  caused a MemoryError, a timing failure and a SQLite I/O error, and the gate of record passed on
  attempt 4. (`2026-10-06-sp14-sample-route-onboarding-reflection.md:257`)
- "Host contention from other lanes' gates, not the change, set the gate run count: 667-H took 7
  runs and 697-H took 4." (`2026-10-14-it8-11-residuals-reflection.md:259`)
- `quiet_busy` waits held one full gate for hours, and GS2 needed 18 tries for one H1-2.
  (`2026-10-17-run-parameters-reflection.md`, memory `gs2-plan-state.md`)
- EM1's Playwright loop and other lanes' gates caused three `IDLE_GATE` timeouts in S14.
  (memory `p23-s14-plan-state.md`)

**It does not fix these, on any number of machines.**

| Problem | Evidence | Why a node doesn't help |
|---|---|---|
| A baseline that is already red | MFU1: two H1-2 passes of 1982 s and 1956 s, each "red on tests that MFU1 does not touch" | The red travels with the commit |
| Windows-only races | A reader race fails 1 of 5 runs with nothing else running | Same OS, same race |
| Landing races | `publish_refused` and `land_fail:changed` when `main` moves | Landing still happens in one place, and longer jobs land on older bases |
| Old bases | A first full gate failed on a race `main` had already fixed; five files then needed merging | Remote runs make this more likely, so `send` has to refuse stale bases |
| Review cost | "116 paid review rounds, the single largest process cost" | Spend, not compute |

Load also explains only part of the reds: MFU1's rig with 24 burners did not reproduce one
failure. Expect fewer retries and shorter waits, not green gates.

**<member host> is not a second <hub host>.** It has an i3-7100 with 2 cores and 4 threads, against <hub host>'s 12
cores and 24 threads. It has 24 GB of RAM, a SATA SSD with 105 GB free, and Wi-Fi only. Agent
sessions mostly wait on the model, so <member host> should suit planning and review. Full Zorivest gates
will be much slower there. I have not measured by how much, so rollout phase 2 measures it.

## 3. Architecture

### 3.1 Shape

```
             GitHub  <-- push (<hub host> only, human-gated, as today)
                ^
                |
   +------------+---------------+
   |  <hub host> (publisher)         |   Signing key, GitHub, VMware, Zorivest backend
   |  fleet place/send/collect  |   Plans can also run here: it is a node too
   |  existing land route       |
   +----+------------------+----+
        | ssh + git        | ssh + git     <hub host> always initiates.
        v                  v               Nodes never connect to <hub host> or to each other.
   +---------------+   +---------------+
   | <member host>         |   | next node     |   Same install script, one more row in the list
   | P:/av-kit     |   | ...           |
   | P:/zorivest   |   |               |
   | P:/.agent     |   |               |
   | run store     |   |               |
   | monitor, mail |   |               |
   +---------------+   +---------------+
```

### 3.2 Five rules

1. **Same paths everywhere.** Every node has a real `P:` holding the same repos. The tooling
   hard-codes it (24 non-Markdown files under Zorivest `tools`, `.claude` and `.agent/skills`,
   5 in av-kit, and 61 av-kit pytest tests), and so do the registry, receipts and memory folders.
2. **One checkout per project per node.** `P:/av-kit` on a node sits at a detached HEAD on the
   job's commit, and one job holds it at a time. The node decides that, not <hub host>: a reservation
   file is created atomically before checkout and held until the job is finalized (section
   3.4). That removes worktree pools and `node_modules` junctions, which have broken repeatedly.
   A plan that needs parallel work uses another node.
3. **A run stays on its node.** Session transcripts, the run store and logins are local. If a node
   dies, its snapshot is collected and a new run starts somewhere else. Runs never migrate.
4. **The node owns the job record.** <hub host> reads it and never holds a competing copy of job state.
5. **Unclear state stops for a human.** A stale job is never retried automatically and is never
   sent twice. Precedent: "Resumes will be always manually invoked by human from IDE."

### 3.3 Placement at planning time

None of the seven reviewed projects places work at planning time. The prior art is GitHub Actions
and Buildkite, where a worker must hold all of a job's labels or tags. Buildkite discourages
hostname targeting because an offline agent blocks the job, so the default here is `prefer`, with
`pin` for real constraints.

The placement unit is the plan, not the row. Rows that need cross-row state have not delegated
well (`2026-10-17-run-parameters-reflection.md`), and plans are a natural boundary. Gate jobs
(section 3.4) cover the row-sized case.

**The node list** goes in the registry repo, so adding a node is a human edit (M-3, M-13):

```yaml
# P:/.agent/nodes.yaml
nodes:
  <hub host>:
    ssh: null
    labels: [windows, desktop, vmware, zorivest-backend]
    slots: {agent: 5, heavy: 1}
    gate_factor: 1.0
    projects: [av-kit, zorivest]
  <member host>:
    ssh: <member host>
    labels: [windows, desktop]
    slots: {agent: 3, heavy: 1}
    gate_factor: null           # null until phase 2 measures it; null means no heavy work
    projects: [av-kit, zorivest]
```

**The plan block** goes in frontmatter beside `run_parameters`. It records facts, not authority:

```yaml
placement:
  needs: [windows, desktop]     # every label must match
  weight: heavy                 # light = mostly model wait; heavy = full gates, builds
  est_gate_minutes: 60          # measured on <hub host>
  prefer: <member host>                 # soft
  pin: null                     # hard: only this node, or stop
  node: <member host>                   # chosen by fleet place
  reason: "free heavy slot; <hub host> busy with lane p23-s14"
```

**How the planner fills it in**, from what `create-plan` already knows:

| Plan contains | Becomes |
|---|---|
| Electron, Playwright or capture rows | `needs: desktop` |
| Any gate, test suite or build, including Zorivest `--scope meu` (which still runs whole Vitest and pytest suites) | `weight: heavy` |
| Only reading, writing, planning and review, with no gate | `weight: light` |
| `vm-harness` rows | `needs: vmware`, so <hub host> today |
| Rows that need the running Zorivest MCP or backend, or the real databases | `needs: zorivest-backend` |
| Rows that edit `P:/.agent` or the framework | `pin: <hub host>`, because a registry edit during a gate caused `run_not_stable` |
| Files that overlap another lane card | Stays a planning problem: another machine doesn't remove a land conflict |

**The matcher** is deterministic and short:

```
candidates = nodes where
    project is listed, all needs are in labels, doctor is fresh, no HOLD file,
    the project checkout is free, a slot of the job's weight is free,
    and (weight is light or gate_factor is set)
if pin:        candidates = candidates that are the pin
if none:       write node: none, stop, and tell the human
rank by:       prefer
               then shortest estimated finish (est_gate_minutes x gate_factor + work running)
               then not-<hub host> for light work, which keeps <hub host>'s cores free
```

**Planning a plan.** A plan job is a job with `weight: light` and `needs: []`. The human can name the
node, or `place` picks one. Plan jobs use Claude only, following the ruling against Codex for
planning (memory `feedback-no-codex-for-planning.md`).

A plan job always runs with `exec_after_plan: false` and `commit_plan: false`, overriding
`create-plan`'s defaults of `true`. Both overrides go into the brief and into the carriers it
generates. Without the second one, the run would reach the plan-commit step, which calls
`commit_batch.py`; that refuses a detached HEAD, and nodes have no signing key anyway. So the run
stops at `PARKED:approved` without committing. The approved plan comes back through the fleet
snapshot, and <hub host> commits it under authority that can be verified on <hub host>. Its output is the plan, including the `placement` block for execution.
Execution is a separate `exec` job, started on the recorded node with its own authority
(D-3). Planning can therefore run on one node and choose another for execution.

The matcher's checks of free checkout and free slot are advisory, because they run on <hub host>.
The node's admission step in section 3.4 is the authoritative check.

**Recheck at the start.** The start-time check is the only one that counts
(`2026-10-15-scheduled-credits-runs-reflection.md`). `send` reruns the matcher. If the chosen node
no longer qualifies, `send` refuses and reports why. It does not move the job on its own, because
the human approved that placement.

### 3.4 Job kinds and lifecycle

| Kind | Runs | Output |
|---|---|---|
| `gate` | A fixed command, no model. This is the "e2e test like a subagent" case | A result file per `cloud-local-collaboration.md` §5.2 |
| `plan` | `/create-plan` through the existing dispatch or credits route | Plan files as a commit |
| `exec` | `/execution-session` through the existing dispatch or credits route | Work tree as a commit, plus a result file |

**`fleet send <plan>` on <hub host>** stages the job:

1. Refuses unless `doctor` is fresh, the node has no HOLD file, `P:/.agent` and the framework
   match, and the base is current. These checks are advisory. The node's admission step decides.
2. Pushes the commit: `git push <member host> <sha>:refs/jobs/<id>/in`.
3. Copies the brief and manifest to `{{RECEIPTS_DIR}}/fleet/<id>/` on the node.
4. Over ssh, registers the node's scheduled task. A `gate` job is also started here. A `plan` or
   `exec` job is started on the node under D-3, because its authority has to be verifiable there.

If ssh drops during step 4, the outcome is `unknown`. `status` looks the job up by id, and `send`
refuses an id that was already used. This matches the existing `accepted_pending` handling.

**Authority for model jobs.** The credits launcher checks a brief's `run_parameters`
authorization against the original human message, which it reads from the local session
transcript (`run_parameters.py` `_load_transcript`, `_verify_reference`). A grant issued in a chat
on <hub host> can't be verified on a node. Copying transcripts would defeat the check, and a
missing-transcript bypass would remove it. So a `plan` or `exec` job is authorized in a Claude
session on the node: the human opens one through Remote-SSH or at the console, and their message lands
in the node's own transcript. `Start-CreditsRunTask.ps1` then runs there unchanged, under that
project's `credits_start_policy`. Subscription and Codex dispatch jobs follow the same rule.

**Work that needs `main` stays on <hub host>.** A node's `exec` brief ends the run at the existing
`handback` stop, before the steps that need `main`, signing or GitHub: `commit_batch.py`, land and
push. <hub host> does those after collecting.

**The launcher on the node:**

1. **Admission**, atomic and local:
   - Creates `P:/.fleet/reservations/<project>.json` with create-new semantics. If the file
     already exists, the launcher refuses with `checkout_busy`.
   - Takes a slot the same way, as `P:/.fleet/slots/<weight>-<n>.json`.
   - Rechecks the HOLD file, the idle console for desktop jobs, and the `P:/.agent` and framework
     HEADs named in the manifest.

   The reservation and slot are held until release (step 7). Only `fleet release`, run by a human,
   removes them early. An `unknown` job keeps its reservation until it is reconciled.
2. Checks out the commit, detached.
3. Re-installs dependencies only when a lockfile hash changed, using each project's commands from
   section 4.4.
4. Runs the existing wrapper with its existing stop classes: `Invoke-CodexDispatch`,
   `Invoke-ClaudeDispatch`, or the credits launcher and monitor.
5. **Finalization barrier.** The launcher waits for the monitor to classify the run against the
   live checkout. It then preserves the run:
   - **Index commit.** `write-tree` of the real index, parented on HEAD. It is written only when
     the index differs from HEAD, so a separately staged version survives.
   - **Work commit.** A temporary index built with `add -A`, parented on the index commit or
     HEAD, then `commit-tree`. It becomes `refs/jobs/<id>/out`.
   - **Export check, before any object is written.** `add -A` reads `.gitignore` and
     `.git/info/exclude`. The installer writes the fleet exclude list into the latter, covering
     `.env`, `.mcp.json`, `settings.local.json`, `*.key` and credential files. Every path that
     differs from HEAD is then checked against that denylist and scanned for secret patterns.
     `commit-tree` runs no hooks, so this check takes their place. A hit means `export_refused`:
     the launcher writes nothing and keeps the checkout and reservation for a human.
   - **Failure artifacts.** Each project names its ignored evidence paths, such as Playwright
     `test-results` and JSON reports. The launcher copies them to
     `{{RECEIPTS_DIR}}/fleet/<id>/artifacts/` before any reset, as `cloud-local-collaboration.md`
     §3.2 requires.
6. Writes `result.json` with the run class and the full IDs of the out commit, its tree and the
   index commit. It checks that `refs/jobs/<id>/out` resolves to those IDs, then sends mail
   through `P:/.agent/notify`.
7. **Release.**
   - The launcher resets the checkout and frees the reservation only for finished classes: a
     completed `gate`, `done`, `done_unverified` and `handback`.
   - Every other class keeps the checkout as it is for a human. That covers `parked`, `decision`,
     `sleep_death`, `billing`, `background_wait_exit` and `export_refused`, and a resume
     continues in the same checkout.
   - If preservation, verification or the reset itself fails, the launcher keeps the checkout and
     the reservation.
   - `fleet restore <id>` puts a released job back by checking out the work commit and resetting
     the index to the index commit.

The task survives a Wi-Fi drop, and the credits runs have already proved this launch route: 19
scheduled launches with 0 gate failures.

**`fleet collect <job>` on <hub host>** runs
`git fetch --no-tags <member host> refs/jobs/<id>/out` and checks the fetched commit and tree against the
IDs in `result.json`. It records those IDs in <hub host>'s copy of the result and copies the
artifacts. From then on, landing uses the recorded IDs, never `FETCH_HEAD`, which the next fetch
overwrites. The node keeps the `out` ref until the job lands or the human disposes of it.

**Landing** differs by project, because the two land routes differ:

- **Zorivest.** `lanes.py` refuses a detached HEAD and needs a registered worktree on
  `lane/<slug>`, and `commit_batch.py` binds to a branch parent. So `collect` turns the node's
  remote card into a normal lane on <hub host>: a <hub host> worktree on `lane/<slug>`, with the branch
  created at the out commit (a new `lanes.py claim --from <commit>`). From there, <hub host> runs
  today's integration procedure unchanged: the journal, the approved verdict bound to the final
  tree, and `commit_batch.py` writing signed `main`. A node's gate result can serve as the gate
  of record only when it binds the identical tree ID, which needs the journal to accept a
  receipt by tree ID. Otherwise a new `gate` job runs on the integrated tree.
- **av-kit.** av-kit has no lanes, so <hub host> brings in only the job's change, base to out:
  - <hub host> runs `git merge-tree --write-tree --merge-base=<job base> main <out-commit>`. This
    builds the merged tree without touching the working tree. If `main` still equals the job
    base, the result is simply the out tree.
  - A conflict stops the landing for a human.
  - Otherwise <hub host> checks the merged tree out into a clean `main` working tree and commits it
    through the normal hooks and signing. The commit must have the `main` the merge was computed
    against as its parent.
  - Applying the whole out tree is never allowed, because it would silently revert changes
    <hub host> made to files the job never touched.
  - No ref is created on <hub host>, so its graph still shows only `main` (memory
    `no-branches-main-only`).
- **If `main` moved**, the merged tree gets a fresh `gate` job and the usual review before
  landing. `cloud-local-collaboration.md` §3.3's code-identity check applies unchanged. Phase 6
  includes a case where <hub host> and the node change different files and both changes must survive.

**Remote lane cards (Zorivest).** `send` writes a card of kind `remote`, with the node and job
id but no worktree, so `lanes.py list` in `create-plan` still shows work running elsewhere.
`status` refreshes its heartbeat, so the 6-hour stale rule fires only when the node stops
reporting. `collect` converts it into a normal worktree card. `lanes.py` therefore gains three
things: the remote card kind, `claim --from`, and journal acceptance of a gate receipt by tree ID.

**Working directly on a node.** The human can open a node through Remote-SSH or at its console and run
a session there:

1. **Before any work**, `fleet attach <project>` takes the same reservation and slot as launcher
   step 1, so placement and the launcher see the checkout as busy for the whole session.
2. **At the end**, `fleet snapshot` finalizes that reservation through steps 5 to 7. It refuses
   if the session doesn't hold the reservation.

<hub host> collects the result the same way. Nothing on the node depends on <hub host> being on. Phase 5
tests a `send` made while a direct session holds the checkout; it must be refused with
`checkout_busy`.

### 3.5 Where state lives

| State | Lives on | Reaches other machines by |
|---|---|---|
| Code, plans | Git, wherever the job is | Push from <hub host>, fetch by <hub host> |
| `P:/.agent`, `P:/agentic-framework` | <hub host> is the source | `fleet sync`, refused while a job runs on that node |
| Run store, dispatch receipts, transcripts | The node | `status` reads it; `collect` copies the result |
| Reservations and slots (`P:/.fleet`), `os_lease`, the quiet-machine probe | The node | Not shared, because they guard that machine's checkout and load |
| Remote lane cards (Zorivest) | <hub host> | Heartbeat refreshed by `status`; converted to a local lane by `collect` |
| Logins, keys, SMTP credential | The node, created there | Never leave it |
| Claude memory | <hub host> is the source | One-way in `fleet sync`. Node-written memory is lost in v1, so lessons go in the repo's reflection |

### 3.6 What gets added to the framework

| Path under `core/` | What |
|---|---|
| `tools/fleet.py` | `doctor`, `place`, `send`, `status`, `collect`, `sync`, `attach`, `snapshot`, plus the human-only `release` and `restore` |
| `.agent/skills/fleet/SKILL.md` | The contract, in the style of `claude-credits/SKILL.md` |
| `.agent/skills/fleet/Start-FleetJob.ps1` | Node launcher, built on `CreditsRun.psm1`'s scheduler adapter |
| `.agent/skills/fleet/Install-FleetNode.ps1` | Idempotent install of section 4, with `-WhatIf` and before/after records |
| `.agent/docs/node-setup.md` | Human steps, next to `macos-setup.md` |
| `.agent/workflows/create-plan.md` | Step 0 fills in `placement` when `nodes.yaml` exists; otherwise nothing changes |
| `.agent/workflows/cli-dispatch.md` | A "where" step after "which agent" |
| `tools/lanes.py` | Remote card kind, `claim --from <commit>`, journal acceptance of a gate receipt bound by tree ID |
| `ADOPTION-GUIDE.md`, `UPDATE-CHECKLIST.md`, `MANIFEST.md` | An optional module. A project without `nodes.yaml` sees no change |

`UPDATE-CHECKLIST.md` treats the framework as refreshed from Zorivest. This feature starts in the
framework, as the human asked, so the checklist has to mark it framework-origin or a refresh could
overwrite it.

**Simplicity limit.** If `fleet.py` passes about 600 lines, or anything on a node needs a process
that runs between jobs other than the existing Monitor task, stop and redesign.

## 4. Prerequisites for a node

Versions are <hub host>'s, read 2026-10-31. <member host>'s state comes from the same day's WinRM inventory.
Keep CLI versions equal across nodes, since the credits probe kit has to be re-run after a CLI
upgrade. `winget` is missing from the `<member user>` account's PATH on <member host>, so the install uses direct
installers. The `<console user>` profile hasn't been checked.

### 4.1 Machine

| Item | Value | <member host> today |
|---|---|---|
| OpenSSH Server | `Add-WindowsCapability`, automatic start, key only, firewall rule scoped to <hub address> | Not installed, port 22 closed |
| Default ssh shell | PowerShell, set in `HKLM:\SOFTWARE\OpenSSH` | Not set |
| Account | The console user (D-1) | `<console user>`, active at console |
| `P:` drive on the SSD | D-5 | Absent |
| Long paths | `LongPathsEnabled=1`, same as <hub host> | Not checked |
| Disk | At least 40 GB free on the SSD after install. Never use the HDDs for repos | 105 GB free on C: |
| Sleep on AC | Off | Already off |
| Windows Update | Active hours set so a restart doesn't land mid-run. A reboot needs a console logon before jobs run | Not checked, `AutoAdminLogon=0` |
| Receipts | `C:\Temp\av-kit`, `C:\Temp\zorivest` | Exists: not checked per project |

Follow the local network notes: record state first, use named reversible rules, keep before/after
records in `reports/`, leave firewall profiles on and keep the log collector working.

### 4.2 Toolchain (required)

| Tool | Version | Install | <member host> today |
|---|---|---|---|
| git with Git Bash | 2.56.0 | Present; set `core.autocrlf=true` (the av-kit byte hash depends on it), `commit.gpgsign=false`, and the same `user.name` and `user.email` | Present |
| PowerShell | 7.6.9 | MSI | Missing |
| Node, npm | 24.19.0, 11.6.2 | MSI | Missing |
| uv, uvx | 0.12.5 | Standalone installer. Zorivest requires uv 0.12.5 or newer | Missing |
| Python for the projects | 3.12.12 | `uv python install 3.12.12`. Both projects' `.venv`s on <hub host> run 3.12.12, and Zorivest pins it in `.python-version` | Missing |
| Python, `py` launcher | 3.14.7 | python.org installer, for scripts run outside uv, such as hooks and `P:/.agent/tools` | Missing |
| Go | 1.25.4 | MSI. Needed only for Zorivest TUI work (`tui/go.mod`); `doctor` checks it when the job touches `tui/` | Missing |
| .NET SDK | 8.0.427 | Needed to `dotnet publish` the capture-picker stub | Present, version not read |
| ffmpeg | Match <hub host> | Present at `C:\Windows\ffmpeg.exe` | Present, version not read |
| ripgrep, fd, jq | 15.2.0, 10.4.2, 1.8.2 | Copy binaries or use scoop | Missing, not confirmed for fd and jq |
| rtk | 0.42.2 | Copy `~/bin/rtk.exe`, then `rtk init -g` | Missing |

`pnpm` 10.28.1 and `bun` 1.3.13 are on <hub host>. I didn't confirm either project needs them, so
install them only if a gate asks.

### 4.3 Agent CLIs (required)

| CLI | Version | Install |
|---|---|---|
| `claude` | 2.1.312 | `npm i -g @anthropic-ai/claude-code@2.1.312` |
| `codex` | 0.165.0 | `npm i -g @openai/codex@0.165.0` |
| `cswap` | 0.29.0 | `uv tool install claude-swap==0.29.0` |
| `ccswap` | 0.42.1 | `uv tool install ccswap==0.42.1` |

### 4.4 Repos and shared tooling

| Path | Seeded by | Notes |
|---|---|---|
| `P:/.agent` | ssh push from <hub host> | It has no remote today. `notify.local.json` is per machine. Compiled registry and project overlays must stay in sync or the resolver fails with `overlay_compiled_drift` |
| `P:/agentic-framework` | ssh push | Required: av-kit gates pin its HEAD in the result (`cloud-local-collaboration.md`) |
| `P:/av-kit` | ssh push (11 MB pack) | Then `uv sync --frozen --all-packages` (the root has no dependencies of its own; its three packages are workspace members), `npm ci --prefix ui`, `npm ci --prefix mcp-server`, and the capture-stub `dotnet publish`. `.mcp.json` is created locally and listed in the fleet exclude. Keep `ELECTRON_RUN_AS_NODE` unset |
| `P:/zorivest` | ssh push (192 MB pack) | Then `uv sync --frozen --all-packages --extra bundle`, the selection Zorivest's own gate snapshot uses (`tools/validate_codebase.py`). The tests import `ib_async` and `alpaca-py` unconditionally; the libraries are needed, but TWS itself isn't. Then `npm ci --prefix ui` and `npm ci --prefix mcp-server`. `_inspiration` and local databases stay behind |

`doctor` doesn't stop at checking that tools exist. It imports each project's packages
(for Zorivest, `ib_async` and `alpaca` too),
runs one cheap command per gate stage, checks the hooks named in `.claude/settings.json`
resolve, and rebuilds an environment that is missing even when the lockfiles haven't changed.

**What each project can run today.** Only Zorivest has the full stack the model-job design
relies on. av-kit has `Invoke-CodexDispatch.ps1`. It has no `Invoke-ClaudeDispatch.ps1`, no
`claude-credits` skill or config, and no `run_parameters.py`, `agent_config_integrity.py`,
`lanes.py` or `commit_batch.py`. Copying the framework repo to a node doesn't install them.

| Job kind | av-kit | Zorivest |
|---|---|---|
| `gate` | Yes | Yes |
| `plan`, `exec` through Codex | Yes | Yes |
| `plan`, `exec` through Claude subscription or credits | Only after av-kit adopts `claude-credits`, `run_parameters.py` and `Invoke-ClaudeDispatch` from the framework | Yes |

That adoption is a separate framework-adoption change in av-kit and a prerequisite for those
rows. It isn't part of this proposal.

No repo on a node gets an `origin`. Zorivest's gate tools don't read `origin/main`; `commit_gate.py`
and `tools/deps` call `ls-remote`, so dependency batches stay on <hub host>.

`launcher.env.json` in each credits store sets `AGENT_MODEL_REGISTRY_HOME=P:/.agent`, because
scheduled tasks don't see session variables.

### 4.5 User-level config

| Item | Handling |
|---|---|
| `~/.claude/CLAUDE.md`, `RTK.md`, `skills/` | Copy |
| `~/.claude/settings.json` | Copy after review; check `remoteControlAtStartup` and `permissions` |
| `~/.claude.json` | Don't copy, because it holds account state. Recreate MCP entries with `claude mcp add` |
| `~/.codex/config.toml`, `AGENTS.md` | Write a node version without <hub host>'s machine paths and unused servers |
| `~/.claude/projects/*/memory` for both projects | One-way sync. 262 files, 1.6 MB. A regex scan for key and password patterns found nothing, which doesn't prove the files are clean, so the human should accept this under D-2 |

### 4.6 MCP servers

| Server | Decision |
|---|---|
| serena, sequential-thinking | Required |
| avkit | Required for av-kit, built on the node |
| graphify | Optional. It is served from <hub host> on localhost, and `create-plan` already records `not_applicable` when it is absent |
| pomera | Optional, and without copied API keys. HDP then falls back to harness WebSearch and records the rung |
| zorivest | Only with the backend running, which is why `zorivest-backend` is a label |
| headroom, firecrawl, hackernews, backup, ebay, genechat, opencravat, video-audio, github | Excluded from v1 |

### 4.7 Created on the node by a human (never copied)

| Credential | How | Why not copy |
|---|---|---|
| Claude subscription, both accounts in `cswap` | Log in on the node at its console, then `cswap add` | Refresh tokens rotate, so "two machines can't share the same refresh token" ([#21765](https://github.com/anthropics/claude-code/issues/21765)). Don't use `cswap export`/`import` for credentials. `cswap import-usage` looks like the right way to share usage readings; test it |
| Codex | Device-code login, or `ssh -L 1455:localhost:1455` then `codex login` | OpenAI's CI guide says not to share one `auth.json` across machines (as reported by [LaoZhang](https://blog.laozhang.ai/en/posts/codex-headless-login); see also the [auth docs](https://learn.chatgpt.com/docs/auth)) |
| Credits key | A new Console key named for the node, at `~/.anthropic/claude-credits.key`, with restricted ACLs | One node's key can then be revoked alone |
| SMTP password | `agent_notify.py setup` stores it in Credential Manager, plus a `notify.local.json` for the node | The password is never in a file by design |
| M-1 credits gate receipt | Run `probes/run_gate.py` on the node | The receipt is per environment and binds the project |
| Agent-config baseline | `agent_config_integrity.py accept` on the node | The state is per machine; a stale baseline refuses FullAccess dispatch host-wide |
| Zorivest `.env` | Write a test-safe one once a gate shows which names it needs | Don't copy <hub host>'s. It is untracked and I didn't open it |

### 4.8 VS Code

On <hub host>: a `Host <member host>` entry in `~/.ssh/config` with a dedicated key, plus
`"remote.SSH.remotePlatform": {"<member host>": "windows"}`. Remote-SSH installs its own VS Code Server on
the node and doesn't attach to a VS Code already running there. It is for looking at a node and
working on it directly. Jobs don't need it.

### 4.9 Deliberately excluded

- **`gh`, GitHub credentials, `origin`, the SSH signing key.** This enforces "this machine is the
  only one pushing".
- **VMware, TWS and real product databases.** Those are <hub host> labels.
- **Hosted Windows task state from <hub host>.** `\Zorivest\Credits\*` is created on the node by its
  own install.
- **Other agent CLIs.** That covers aider, mistral-vibe, gemini-cli, opencode, crush, auggie,
  qwen-code, continue, droid, notebooklm, cursor, ollama and the rest. Add one only when a plan
  needs it.

## 5. Rollout

Each phase has a test that has to pass before the next one starts.

| Phase | Work | Passes when |
|---|---|---|
| 0 | Decisions D-1 to D-6 | Answered |
| 1 | `Install-FleetNode.ps1` on <member host>; ssh, `P:`, tools, repos, logins | `fleet doctor <member host>` green, including negative checks: no `gh`, no `origin`, no signing key |
| 2 | `gate` job: av-kit headless gates, then one Zorivest gate | Same test counts as <hub host> at the same commit, and `gate_factor` recorded from real times |
| 3 | `gate` job: av-kit E2E in the console session through an Interactive task | Windows paint and the suite finishes. If it fails, drop `desktop` from <member host>'s labels and carry on |
| 4 | On Zorivest, one small model job each, started from a Claude session on <member host>: Codex, Claude subscription, Claude credits | Authority verifies from the node's transcript, and credits usage appears correctly in the Console before any larger credits job |
| 5 | `plan` (forced `exec_after_plan: false` and `commit_plan: false`; plan committed on <hub host>) then `exec` on a small Zorivest plan, ending at `handback`; collected into a <hub host> lane with `claim --from` and landed through `commit_batch.py` | **Independence test:** <hub host> is off for part of the run, the job finishes, mail arrives and `collect` works after <hub host> returns. **Admission test:** a second `send` to the same checkout is refused with `checkout_busy`. **Export test:** a planted `.env` is refused with `export_refused` |
| 6 | av-kit `exec` through Codex, landed with `merge-tree` and a normal commit on <hub host>. av-kit Claude jobs wait for the framework adoption in section 4.4 | With `main` unmoved, the landed tree equals the collected tree. With `main` moved, a <hub host> change to another file survives the landing |
| 7 | A second node, or a VM standing in for one | Only the install script and one `nodes.yaml` row were needed, with no code change |

Untested so far, and each is covered by a phase above:

- `git push` over ssh with PowerShell as the default shell (phase 1)
- The `DOS Devices` mapping on build 19045 (phase 1)
- Electron in an Interactive task on the active session (phase 3)
- Credits billing for a task started over ssh (phase 4)
- Separate logins not disturbing each other. The docs and the issue reports point that way, but
  it's an inference (phase 4)
- `executor_worktree: false` and the `handback` stop in the Zorivest workflow (phase 5)
- `lanes.py claim --from` and gate receipts accepted by tree ID (phase 5)

**Exposure I found and did not change.** <member host>'s WinRM settings are looser than the fleet needs, and
the local WinRM helper stores the login it uses, where a <hub host> agent can read it. Once ssh works,
restrict WinRM to <hub host>'s address, after checking what the local ops scripts need. <member host>'s antivirus
settings also favour gate speed over protection, which matters under agents running with
`bypassPermissions`.

## 6. Inspiration review

A subagent reviewed the seven projects at source level; most findings come from repo docs rather
than code. It corrected several claims in the list the human pasted, noted below.

| Project | Fit | Takeaway |
|---|---|---|
| [distributed-infra](https://github.com/motethansen/distributed-infra) (0★) | macOS and Linux only as far as found. Queue is now rqlite, not SQLite-first | Capability matching with hard pin and soft preference. Stale goes to `needs_human`. **Avoid:** an empty secret disables auth |
| [Paseo](https://github.com/getpaseo/paseo) (22.6k★) | Best Windows and licence fit | `outcome: unknown` and idempotency keys. The caller picks the host; no scheduler |
| [Kandev](https://github.com/kdlbs/kandev) (1k★, AGPL) | **SSH workers are Linux/macOS only**; Windows is control plane only | Session-identity check on reconnect; env allowlist. **Avoid:** host git credentials on workers |
| [Fusion](https://github.com/Runfusion/Fusion) (1.3k★, early preview) | Needs a shared database for its mesh | Chosen node snapshotted on the task. Lease-epoch fencing is more than needed here |
| [AI Maestro](https://github.com/23blocks-OS/ai-maestro) (840★) | WSL2 only on Windows. Measured about 235 MB idle plus 200 MB per Claude, not the 100 MB in its README | **Avoid:** no app auth on 0.0.0.0; blanket `Bash(*)` |
| [thurbox](https://github.com/Thurbeen/thurbox) (115★) | Closest in shape: system `ssh`, native Windows hosts through psmux | Hosts as data, system ssh, host holds the record. psmux is the fragile part |
| [Cotal](https://github.com/Cotal-AI/Cotal) (373★) | NATS JetStream with a manager per host | Journal before effect. **Avoid:** telemetry on by default; detached Claude bypasses permissions |

**Why not adopt Paseo.** It has no scheduler or capability model, its daemon must already be running
on each worker, and resume is best-effort. Nothing in it enforces a linear `main` or
workstation-only push. We would swap our PowerShell wrappers and JSON state for a large product and
still have to build placement, ambiguity handling and landing.

**Taken into this design:** requirement matching with pin and prefer, recording the chosen node and
reason, hosts as data over system `ssh`, a host-side record, `unknown` as an outcome, and stale
going to a human.

**Left out for now:** automatic account failover with cooldowns. `cswap auto` already exists, and
none of the reflections or memories record an account-switching failure.

## 7. Decisions

Per `.agent/docs/human-decision-protocol.md`. Research used the Pomera MCP (Tavily engine) and
direct reads of vendor docs. D-1 to D-6 fail the obviousness test or hit the mandatory list, so
they need the human. A-1 to A-7 passed and are logged at the end.

### D-1: Make <member host> a trusted remote, and run jobs as `<console user>`?   [governance-value] [planning]

**Recommendation:** A. Key-only ssh from <hub host> into `<console user>`. It is the only account that has a
desktop, and the existing credits tasks start with `LogonType=Interactive`, so they only run for a
logged-on user.

**Mandatory hits:** M-13 (a new trusted remote, and agents running with wide permissions there),
M-10 (human steps at the console).

**Why not the others**

| Option | Pros (vs. A) | Cons (vs. A) | Sources |
|---|---|---|---|
| ✅ A: `<console user>` | — | — | `CreditsRun.psm1:795-796`; `vm-harness/SKILL.md:197,248` |
| ⚠️ B: `<member user>` for jobs | Separates agents from the desktop profile | No console session, so Interactive tasks won't start and there are no desktop jobs. A switch to S4U needs a credits change and loses network credentials | Stack Overflow on interactive tasks; openclaw #143757 |
| ❌ C: A dedicated `agent` account with autologon | Cleanest isolation | Takes the workstation away from the human, and stores a logon password | Superuser 1629317 |

**Precedent:** the memory note on <member host>'s console user; Zorivest `vm-harness` (Session 0 "paints nothing and never
exits"; use a task as the logged-in user).

**Research:** Tavily. Windows interactive tasks need the user logged on. Session 0 hosts no GUI.

**Reversibility / risk:** two-way. Remove the key and the sshd rule. The real risk: an agent with
`bypassPermissions` can read all of `<console user>`'s profile and every drive, and it is an admin account.
<hub host> has the same exposure today, but <member host> is the human's personal desktop. I haven't looked at what is
on it. Before phase 1, move anything sensitive out of agents' reach or tell me to pick B.

**If you do not answer:** nothing gets installed.

### D-2: Which credentials go on a node?   [governance-value] [planning]

**Recommendation:** A. Each node logs in for itself, gets its own Console key, and defaults to the
Claude account <hub host> uses least. There are 2 accounts in `cswap`, and limits are per account, so
both machines on one account would draw one limit.

**Mandatory hits:** M-2 (who may read a secret), M-4 (spend), M-10 (browser logins).

**Why not the others**

| Option | Pros (vs. A) | Cons (vs. A) | Sources |
|---|---|---|---|
| ✅ A: Separate logins and a per-node key | — | — | anthropics/claude-code #21765, #91708; ChatGPT auth docs |
| ⚠️ B: `claude setup-token` on nodes | No rotation trouble. One-year token, already used for VMs | The credits launcher refuses `CLAUDE_CODE_` names, so it needs a launcher change. No `cswap`. A long-lived bearer token sits on disk | Claude Code authentication docs; `claude-credits/SKILL.md` §Schedule |
| ❌ C: Copy with `cswap export`/`import` | One step | Rotating refresh tokens: the first machine to refresh breaks the other, <hub host> included | #21765 |

**Precedent:** `claude-credits/SKILL.md` (key outside git, never printed); memory
`cn7-plan-state.md` (VM uses `setup-token`); `claude-cli-fallback-lessons.md` (limits are per
account).

**Research:** Tavily and vendor docs. Anthropic documents separate config directories per account and
`setup-token` for scripts. Issue reports describe rotation and Windows file-store races. I didn't
find a statement on one person using one subscription on two machines at once, so I'm not asserting
either way.

**Reversibility / risk:** two-way. Log out and revoke the key. Memory sync is included here: 262
files go to the node one way.

**If you do not answer:** the node stops at `gate` jobs, which need no model login.

### D-3: Who may start, resume or fork work on a node?   [governance-value] [planning]

**Recommendation:** A, tiered.

- `gate` jobs start from <hub host> under the plan's approval, because they use no model and spend
  nothing.
- `plan` and `exec` jobs follow today's rule, applied on the node: the human starts them, or an
  agent passes on the human's words from a Claude session on the node, under the project's
  `credits_start_policy`. The authorization has to come from the node's own transcript because
  that is where `run_parameters.py` verifies it (section 3.4). A grant made on <hub host> can't start a
  model job on a node.
- Only the human resumes, and nodes never start jobs on their own.
- The human starts the first credits job from a terminal.

**Mandatory hits:** M-14, M-4.

**Why not the others**

| Option | Pros (vs. A) | Cons (vs. A) | Sources |
|---|---|---|---|
| ✅ A: Tiered | — | — | `Start-CreditsRunTask.ps1`; `claude-credits/SKILL.md` |
| ⚠️ B: Every job asks, gates included | Simplest rule | The human has objected to this kind of step ("should be never happening!"). Loses the subagent feel for E2E | memory `agent-config-baseline-auto-accept.md`, `lessons-process-over-product.md` |
| ❌ C: A standing grant for all jobs | No stops | Unbounded spend across machines, and removes the plan-to-execution gate | `harness-profiles.md` `plan_to_exec_gate: human` |

**Precedent:** "Resumes will be always manually invoked by human from IDE."
`2026-10-15-scheduled-credits-runs-reflection.md`: human authority sits outside the brief.

**Research:** repo precedent decided this one. The vendor pages I found don't address the ssh case.

**Reversibility / risk:** two-way, with one thing to watch. `Invoke-ClaudeCredits` exits 3 inside
Claude Code because such runs aren't covered by credits. Ssh doesn't inherit
`CLAUDE_CODE_ENTRYPOINT`, so it could work as a way around that check. The rule therefore stays:
credits runs start only through `Start-CreditsRunTask.ps1` under the existing policy, and never by a
direct `claude -p` over ssh. Phase 4 checks the Console. A memory says no credits until November,
which lapses tomorrow, so confirm the balance first.

**If you do not answer:** only `gate` jobs started by the human are possible.

### D-4: Amend av-kit's "work, commit and push on main in P:/av-kit only"?   [source-conflict] [planning]

**Recommendation:** A. A full but narrow exception. `AGENTS.md:102` currently allows work, commits
and pushes only on `main` in `P:/av-kit`. A node breaks that in three ways: it works in its own
`P:/av-kit` at a detached HEAD, it writes unsigned snapshot commits, and it receives
`refs/jobs/*`. So the amendment has to name all three. Proposed text for §Commits:

> To `origin`, push only `main`, only from <hub host>. On a node registered in `P:/.agent/nodes.yaml`,
> `P:/av-kit` may be at a detached HEAD on a job commit, the fleet launcher may write unsigned
> snapshot commits under `refs/jobs/<id>/*`, and <hub host> may push and fetch `refs/jobs/*` to and
> from that node. Those refs never reach `origin`. Review, signing and landing stay on <hub host>'s
> `main`. No branches and no worktrees anywhere.

The rule exists to keep work visible on the `main` graph, and this keeps that. Job refs exist
only on nodes, and <hub host> records the collected commit IDs without creating a ref.

**Mandatory hits:** M-3 (edits `AGENTS.md`, and the rule-map hash needs re-pinning).

**Why not the others**

| Option | Pros (vs. A) | Cons (vs. A) | Sources |
|---|---|---|---|
| ✅ A: Amend for `refs/jobs/*` | — | — | Gerrit `refs/changes` (a working namespace outside branches) |
| ⚠️ B: `git bundle` files, no pushed refs | Keeps commit identity and can be incremental | Still needs the detached-work and snapshot parts of the exception. Adds files to create, copy, verify and clean up for every job, where ssh git negotiates the transfer itself | [git-bundle manual](https://git-scm.com/docs/git-bundle) |
| ❌ C: Patches | No refs at all | Loses commit identity, which §3.3's tested-commit check depends on. Binary and mode changes are fragile | `cloud-local-collaboration.md` §3.3 |
| ❌ D: Keep av-kit off nodes | No change | av-kit E2E was the first thing you asked to delegate | Your first request |

**Precedent:** `AGENTS.md:102`; memory `no-branches-main-only`. Zorivest has no such rule, so the
framework reads this per project.

**Research:** Tavily. Gerrit shows custom ref namespaces as an established way to carry work outside
branches.

**Reversibility / risk:** two-way. Job refs can be deleted on the node and nothing reaches GitHub.

**If you do not answer:** `fleet send` and `fleet doctor` refuse av-kit on any node other than
<hub host>, with `avkit_rule_not_amended`. The design proceeds on Zorivest, and av-kit stays local.

### D-5: How does a node get a real `P:`?   [source-conflict] [planning]

**Recommendation:** A, then B if the test fails. A boot-time `DOS Devices` mapping to `C:\P` applies
to all sessions and elevation levels, and needs no disk change. Sources disagree on whether it still
works, so phase 1 tests it.

**Mandatory hits:** none. It's here because the research conflicts and B is hard to undo.

**Why not the others**

| Option | Pros (vs. A) | Cons (vs. A) | Sources |
|---|---|---|---|
| ✅ A: `HKLM\...\Session Manager\DOS Devices` | — | — | Wikipedia SUBST (works from startup); Superuser 1662374 (reported not honored after 21H1) |
| ⚠️ B: Shrink C: and create a real volume | Certain to work, no aliasing | C: has 105 GB free, so this squeezes it, and it is harder to undo | Plain Windows behaviour |
| ❌ C: Replace `P:` with a variable everywhere | Portable to any machine | Touches 29 non-Markdown tool files and 61 av-kit tests, with a large regression surface | Census in `cloud-local-collaboration.md` §4 |
| ❌ D: `subst` at logon | No registry change | Not available at startup and doesn't persist, so it depends on a logon script. It is per logon session | Wikipedia SUBST; Microsoft Q&A |

**Precedent:** `AGENT_MODEL_REGISTRY_HOME` exists but doesn't cover hooks and tests.

**Research:** Tavily. No clear answer for build 19045, hence the test.

**Reversibility / risk:** A is two-way: delete the value and reboot. It needs one <member host> reboot. B is
close to one-way.

**If you do not answer:** phase 1 tries A, then stops and asks before B.

### D-6: What is <member host> for, and may jobs use its desktop while you work there?   [product-preference] [planning]

**Recommendation:** A. <member host> takes planning, reviews and av-kit gates. Zorivest full gates go there
only if phase 2's timing justifies it. Desktop jobs start only when the console has been idle for 10
minutes and there is no HOLD file. Windows may still appear if you come back mid-run.

**Mandatory hits:** none. Only you can weigh interruptions on your own desktop.

**Why not the others**

| Option | Pros (vs. A) | Cons (vs. A) | Sources |
|---|---|---|---|
| ✅ A: Light work plus av-kit gates; desktop when idle | — | — | Inventory; `2026-10-06-sp14` reflection |
| ⚠️ B: Dedicate <member host> to jobs and keep it logged in | Quiet machine, no focus fights | You lose it as a workstation | `cloud-local-collaboration.md` §5.1 |
| ⚠️ C: Headless only | No interruptions | Your first ask, E2E, stays on <hub host> and keeps contending there | memory `p23-s14-plan-state.md` |
| ❌ D: Everything goes to <member host>, including full Zorivest gates | Frees <hub host> most | 2 cores, 24 GB, and three concurrent gates already caused a MemoryError on 62 GB | `2026-10-06-sp14` reflection |

**Precedent:** the memory note on <member host>'s console user: still an in-use desktop. Av-kit's quiet-machine rule
requires no other agent or Electron on that checkout.

**Research:** repo evidence decided this. A manual HOLD and an idle check are my own proposal, with
no outside source.

**Reversibility / risk:** two-way. It is a label and two settings.

**If you do not answer:** phase 3 is skipped, and <member host> gets no `desktop` label.

### Decided without asking

These passed the obviousness test: research or precedent converges, each is a two-way door, none
forks the product, and none is a governance number.

```yaml
decision_log:
  - {id: A-1, stage: planning, question: "Transport?", resolution: autonomous, class: null, mandatory: [],
     chosen: "System ssh, git and Task Scheduler; no daemon or queue",
     source_tag: Research-backed, precedents: ["claude-credits scheduled runs"],
     research: {engine: pomera-tavily, sources: ["thurbox docs", "Paseo connectivity.md", "Kandev executors.md"]},
     reasoning: "Reviewed SSH designs use system ssh or tunnels; the route is proven here by 19 scheduled launches."}
  - {id: A-2, stage: planning, question: "Placement model?", resolution: autonomous, class: null, mandatory: [],
     chosen: "All-labels match with prefer, pin and an ordered rank, chosen per plan",
     source_tag: Research-backed, precedents: ["2026-10-17-run-parameters reflection: rows don't split"],
     research: {engine: pomera-tavily, sources: ["GitHub Actions runner docs", "Buildkite agent targeting", "distributed-infra db.py"]},
     reasoning: "The prior art converges; no scoring system is justified for a handful of nodes."}
  - {id: A-3, stage: planning, question: "Worktree pool on nodes?", resolution: autonomous, class: null, mandatory: [],
     chosen: "One detached checkout per project per node, admitted by a node-local reservation",
     source_tag: Repo-backed, precedents: ["memory gt6-plan-review-state, cn7-plan-state: junction failures", "memory shared-tree-gate-concurrency: one executor per tree"],
     research: {engine: none, sources: []},
     depends_on: "D-4 for av-kit; without it av-kit is refused on nodes (avkit_rule_not_amended)",
     reasoning: "Keeps real node_modules and tests on the P: paths; parallelism comes from more nodes. Autonomous only as the worktree-vs-checkout choice; the av-kit rule exception it needs is D-4."}
  - {id: A-4, stage: planning, question: "Where does run state live?", resolution: autonomous, class: null, mandatory: [],
     chosen: "On the node; <hub host> reads and never shares os_lease",
     source_tag: Repo-backed, precedents: ["os_lease.py is a machine-local kernel lock", "thurbox host record"],
     research: {engine: pomera-tavily, sources: ["thurbox ARCHITECTURE.md"]},
     reasoning: "Independence needs it, and the lease guards that machine's load only."}
  - {id: A-5, stage: planning, question: "gh and GitHub credentials on nodes?", resolution: autonomous, class: null, mandatory: [],
     chosen: "Excluded and checked by doctor", source_tag: USER_EXPLICIT,
     precedents: ["First request: this machine is the only one pushing"], research: {engine: none, sources: []},
     reasoning: "A stated requirement."}
  - {id: A-6, stage: planning, question: "On stale or unknown jobs?", resolution: autonomous, class: null, mandatory: [],
     chosen: "Stop for a human; no automatic retry or migration", source_tag: Repo-backed,
     precedents: ["Resumes always human", "2026-10-15-scheduled-credits-runs reflection"],
     research: {engine: pomera-tavily, sources: ["distributed-infra needs_human", "Paseo outcome unknown"]},
     reasoning: "A repeated send can duplicate spend; state is ambiguous by definition."}
  - {id: A-7, stage: planning, question: "Where does the code live?", resolution: autonomous, class: null, mandatory: [],
     chosen: "agentic-framework core as an optional module; av-kit adopts first, then Zorivest",
     source_tag: USER_EXPLICIT, precedents: ["This request names p:\\agentic-framework"], research: {engine: none, sources: []},
     reasoning: "av-kit is smaller and lower risk, so it goes first."}
```

## 8. Sources

**Repo evidence.** Zorivest reflections and memories named inline; `P:/agentic-framework/core/.agent/skills/claude-credits/`;
`P:/av-kit/.agent/docs/cloud-local-collaboration.md`; `P:/zorivest/.agent/docs/human-decision-protocol.md`;
<member host> inventory receipts `C:/Temp/av-kit/<member host>-inv{1,2,3}.txt`.

**Web.**

- Vendor: [Claude Code authentication](https://code.claude.com/docs/en/authentication);
  [ChatGPT/Codex authentication](https://learn.chatgpt.com/docs/auth);
  [GitHub self-hosted runner routing](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/use-in-a-workflow);
  [Buildkite agent targeting](https://buildkite.com/docs/agent/v3/cli-start#agent-targeting);
  [Gerrit refs/for](https://gerrit-review.googlesource.com/Documentation/concept-refs-for-namespace.html).
- Issue reports: [claude-code #21765](https://github.com/anthropics/claude-code/issues/21765);
  [claude-code #91708](https://github.com/anthropics/claude-code/issues/91708);
  [openclaw #143757](https://github.com/openclaw/openclaw/issues/143757).
- Community: [Wikipedia SUBST](https://en.wikipedia.org/wiki/SUBST);
  [Superuser 1662374](https://superuser.com/questions/1662374/dos-devices-to-directory-aka-permanent-subst-not-honored-after-windows-21h1);
  [Superuser 1629317](https://superuser.com/questions/1629317/how-to-execute-an-interactive-scheduled-task-when-the-user-is-not-logged-in-on-a);
  [Microsoft Q&A on subst](https://learn.microsoft.com/en-us/answers/questions/4366125/disapperaing-map-drive);
  [LaoZhang on Codex headless login](https://blog.laozhang.ai/en/posts/codex-headless-login).
