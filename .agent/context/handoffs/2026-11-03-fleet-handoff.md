---
date: "2026-11-03"
project: "fleet"
meus: []
status: "research_pending"
action_required: "DEEP_RESEARCH_THEN_PLAN"
template_version: "2.2"
verbosity: "standard"
plan_source: "none yet"
agent: "Claude Opus 5.5 (av-kit session av-kit-9b, 2026-10-31 to 2026-11-03)"
predecessor: "docs/proposals/2026-11-01-remote-hosts.md"
---

# Handoff: fleet members that take work over a LAN message system

> **Status**: `research_pending`. Nothing is installed on any member, nothing is committed, and no
> plan exists yet.
> **Action Required**: run the deep research in section 6, then write a plan with
> `/create-plan` from its results.

## 1. How to resume

Open a session in `P:/agentic-framework` and give it this file. The first task is research, not
code. Read, in this order:

1. This handoff.
2. [docs/proposals/2026-11-01-remote-hosts.md](../../../docs/proposals/2026-11-01-remote-hosts.md):
   the ssh design. The human's 2026-11-03 brief (section 2) replaces its transport and control model.
   Its git model (§4), test snapshot (§5) and OS table (§6) still hold.
3. [docs/proposals/2026-10-31-fleet-nodes.md](../../../docs/proposals/2026-10-31-fleet-nodes.md)
   §4 only: the prerequisite inventory for av-kit and Zorivest. The rest of that file is superseded.
4. `core/.agent/workflows/pre-build-research.md` and
   `core/.agent/skills/deep-research-prompting/SKILL.md` for how research runs here.

Both proposal files are untracked (`?? docs/proposals/`). This handoff is untracked too.

## 2. What the human asked for (2026-11-03)

Restated from his message, in his order:

1. **Member bootstrap instructions, templated.** An AI agent running on the member's own machine
   sets the member up and proves it can talk to the fleet's orchestrator. The instructions cover
   the agent tooling and libraries every member needs, plus each project's own dependencies.
   They're a template: one common part, one part per project.
2. **A universal agent communication system,** not tied to Claude Code. The human uses Codex a lot and
   may use more of Cursor's `agent.exe` and the Antigravity CLI.
3. **Members run work through the agent CLIs,** such as `claude` and `codex`.
4. **Windows, Linux and macOS** for every member instruction.
5. **LAN first, possibly without ssh.** If needed, build a client so members can talk to the
   orchestrator and to each other, and ask each other to run things on their native systems.
   The orchestrator doesn't drive a member's machine directly. It gives a member a task, and the
   result comes back over the messaging system. The human expects this to need deep research first.

### How this changes the 2026-11-01 proposal

| 2026-11-01 proposal | 2026-11-03 direction |
|---|---|
| <hub host> runs commands on the host over ssh | <hub host> sends a task message. The member's own agent or client runs it and replies |
| Messaging is the Claude credits store, read over ssh | An agent-neutral message system on the LAN, which every CLI can use |
| Host set up by hand from a checklist | Host set up by an agent on that host, from a template, ending in a handshake |
| Claude `claude -p` only | Claude, Codex, Cursor `agent`, Antigravity, through one adapter each |
| Members only receive work | Members can also ask each other, for example "run the macOS build" |

## 3. What still holds from the earlier work

### Constraints, all still binding

- Only <hub host> pushes to GitHub. Members use local git only, with no `origin`, GitHub credentials or
  signing key.
- Never auto-commit or push. A message never authorizes a commit, push, merge, tag, release or a
  plan-to-execution step. That rule comes from `core/.agent/skills/claude-credits/SKILL.md`, and the
  new system must keep it.
- No secrets, cookies or credentials in a message or a dispatched brief. Logins and keys are created
  by a human at each member's console, never copied (2026-10-31 proposal §4, "Created by a human").
- Claude billing: never set, unset or override `CLAUDE_CODE_ENTRYPOINT`, `CLAUDECODE` or related
  variables to change how a run is billed, and never `cswap switch` to the API-key slot from an
  agent session (claude-credits SKILL rule 8). A run started by an IDE, even with `-p`, didn't draw
  credits in a 2026-10-12 test.
- av-kit: no branches or worktrees on <hub host> (`P:/av-kit/AGENTS.md:102`). Members need a narrow
  exception, worded in the 2026-11-01 proposal §7.
- <member host>: don't disturb its log collector, and don't turn firewall profiles off. Follow
  the local network notes: record state before changing it, use named reversible rules, write
  before/after records in `reports/`.

### The git model (tested in throwaway repos on <hub host>, 2026-11-01 and 2026-11-03)

One `main`, on <hub host>. A member keeps a read-only copy that moves only when <hub host> pushes
(`receive.denyCurrentBranch=updateInstead`, `denyNonFastForwards`). Each job runs in a persistent
worktree slot on a member-only `lane/<slug>` branch. After the agent exits, the member saves the
work as one unsigned commit. <hub host> fetches it with a remote that has no fetch refspec, checks it
with `git merge-tree --write-tree`, squashes it, and makes the signed commit on the human's word.
Test snapshots use a temporary index, so untracked files are included, and go to
`refs/remote-test/<id>`, not a branch. Details and the exact commands are in the 2026-11-01
proposal §4 and §5.

That model assumed <hub host> can reach the member's repo. Under the new direction, research must
settle how commits move: <hub host> pulling from a member's git daemon, the member pushing to a
receive-only ref on <hub host>, or bundles carried in messages. Each has a different trust story.

### Facts learned that the research can build on

| Fact | Source |
|---|---|
| Windows OpenSSH kills every process from a session when it closes, by design. Detached work on Windows needs Task Scheduler, a service, or an always-running member client | [Win32-OpenSSH #1195](https://github.com/PowerShell/Win32-OpenSSH/issues/1195) |
| `claude -p` on a plan login draws from subscription limits. On a linked Console key, monthly API credits can cover it | [Anthropic help, updated 2026-10-07](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan) |
| Claude Code 2.1.312 has background sessions: `claude --bg "<prompt>"` (not `-p`), `claude agents --json --all`, `logs`, `stop`, `attach`, `--resume <id> --bg`. A supervisor keeps them running. No shell command sends a message to a running one | [Agent view docs](https://code.claude.com/docs/en/agent-view), local `claude --help` |
| Claude cross-session messaging (`SendMessage`, `ListAgents`) reaches sessions on another machine only through Remote Control, routed via Anthropic, on a claude.ai login. API keys aren't supported. On one machine it uses a named pipe or socket, and a script can post with `CLAUDE_CODE_MESSAGING_SOCKET` and `CLAUDE_CODE_MESSAGING_TOKEN` | [Cross-session messaging docs](https://code.claude.com/docs/en/cross-session-messaging) |
| Claude-only, so neither of the two rows above meets requirement 2. They may still serve as the Claude adapter's local delivery path | The human's brief |
| The credits stack already has a message model worth generalizing: kinds `info`, `query`, `stop-after-row`, `ruling`; replies `ack`, `applied`, `report`, `decision`; monitor stop classes such as `done`, `parked`, `decision`, `billing`, `timeout` | `core/.agent/skills/claude-credits/SKILL.md`, `tools/credits_msg.py`, `Watch-CreditsRuns.ps1` |
| `ruling` messages check the orchestrator's local transcript, so they can't work across machines as built | `Send-CreditsRunMessage.ps1`, `credits_inbox.py` |
| The credits launcher is Windows-only: Win32 job objects via Add-Type in `CreditsRun.psm1`, Task Scheduler, `ConvertTo-WindowsArgument`, `;` path joins. `New-CreditsSchedulerAdapter` is a seam for other OSes | `CreditsRun.psm1:967` |
| Hardcoded `P:` paths: 6 tracked files in av-kit tooling and 13 in Zorivest `tools/`. A member must not need a `P:` drive | 2026-11-01 proposal §6 |

## 4. Machines and tools at handoff time

| Item | <hub host> (orchestrator) | <member host> (first member) |
|---|---|---|
| Address | <hub address> | <member address> |
| OS | Windows 11 Enterprise 26300 | Windows 10 Pro 19045. The `<console user>` console user is the human |
| Hardware | | i3-7100, 2 cores 4 threads, 24 GB, Wi-Fi, 105 GB free on C: |
| Reach today | | WinRM (see the local ops folder). No ssh server yet |
| `claude` | 2.1.312 | not installed |
| `codex` | 0.165.0 | not installed |
| Cursor `agent` | installed at `%LOCALAPPDATA%/cursor-agent/agent.cmd`, not on the bash PATH | not installed |
| Antigravity CLI | not found | not installed |
| `cswap`, `ccswap` | 0.29.0, 0.42.1 | not installed |
| git, uv, pwsh | 2.56.0, 0.12.5, 7.6.9 | git present; pwsh, uv missing |
| node | 26.13.0 now. The 2026-10-31 inventory recorded 24.19.0, so check which one the projects pin | missing |

The model registry already has Cursor entries (`P:/.agent/model-registry.yaml`, `cursor-task`
and `cursor-agent-cli` keys, for example `agent --model grok-4.7-xhigh`). It has none for
Antigravity.

## 5. A starting shape for each requirement

These are framings for the research and plan, not decisions.

### 5.1 Bootstrap template (requirements 1 and 4)

Two layers, both agent-readable markdown with a machine-checkable manifest beside them:

- **Common member template:** OS detection; package manager per OS (winget or scoop, apt or dnf,
  Homebrew); toolchain (git, Python through uv, Node, pwsh where still needed, rtk, ripgrep, fd,
  jq); agent CLIs; the member client; registry home (`AGENT_MODEL_REGISTRY_HOME`, never `P:`);
  global agent config (`~/.claude/CLAUDE.md`, `RTK.md`, skills, the Codex config); the human-only
  steps, listed as a checklist the agent stops at; and a final handshake with the orchestrator.
- **Per-project manifest:** clone source, dependency commands (av-kit: `uv sync --frozen
  --all-packages`, `npm ci --prefix ui`, `npm ci --prefix mcp-server`, the capture-stub `dotnet
  publish`; Zorivest: `uv sync --frozen --all-packages --extra bundle`, `npm ci --prefix ui`,
  `npm ci --prefix mcp-server`, Go only for TUI work), OS support per project (av-kit's Electron
  E2E needs a desktop session and `ELECTRON_RUN_AS_NODE` unset), required MCP servers, and a smoke
  test that proves the slot works.

The bootstrap agent ends with a report: what it installed, versions, what still needs a human,
and the handshake result. It never handles a credential value. Versions and the full item list
are in the 2026-10-31 proposal §4.

**Open question:** where the template lives. Candidates are `core/.agent/fleet/` in this repo,
adopted by projects like other templates, or the shared `P:/.agent` registry home. The per-project
manifest probably belongs in each project repo.

### 5.2 Universal communication (requirements 2, 3 and 5)

Split the problem in two, because agent CLIs differ most at the second part:

1. **Member to member (transport):** a LAN message bus or broker that every member's client joins.
   It carries task, status, query, reply and result messages, plus small artifacts or references
   to them. It needs discovery, authentication between members, delivery when a member was offline,
   and an audit trail.
2. **Client to agent (delivery):** how a message reaches a running `claude`, `codex`, `agent` or
   Antigravity session, and how the agent replies. Options to compare per CLI:
   - the client owns the agent process and talks to it over a structured protocol (stdin
     stream-json, an SDK, or an agent protocol);
   - the agent pulls through a small CLI or MCP tool the client provides ("fleet inbox", "fleet
     reply"), which every CLI can call if it can run shell commands or MCP;
   - the client stops and resumes the session with the message as the next prompt.

   The pull-tool option is the only one that sounds universal without per-CLI work, so test it first.

A message envelope worth starting from: `id`, `from`, `to`, `kind`, `task_id`, `body`, `refs`
(commit, tree id, receipt paths), `created`, `reply_to`, `requires_human`. Carry over the credits
kinds and stop classes where they fit, and the rule that no message grants commit authority.

Each CLI gets an adapter with the same verbs: start (with brief, model, effort, permission mode,
auth mode), status, peek, deliver message, stop, resume, collect result, and report cost or usage
if the CLI exposes it. The adapter also records how that CLI bills, so the credits rules stay
enforceable.

### 5.3 Members asking members

A request is a task message addressed to another member or to "any member with capability X"
(OS, GPU, desktop session, project slot). The orchestrator stays the only one who lands work on
`main`. A member-to-member request returns test results or artifacts, never a commit to `main`.

## 6. Deep research to run first

Run it through this repo's `deep-research-prompting` skill: it produces prompts for a provider's
web portal, and the human pastes them. Suggested prompts, each with its own output folder:

| ID | Question | Why it matters |
|---|---|---|
| R-1 | Which agent-interop protocols exist and are used now (for example Google's A2A, Zed's Agent Client Protocol, MCP as a transport, others), and which of `claude`, `codex`, Cursor `agent` and the Antigravity CLI support each, natively or through an adapter? | Use a standard instead of inventing a protocol, if one fits |
| R-2 | For each CLI: headless start, resume by id, structured output and input streams, hooks, how to inject a message into a running session, background mode, permission modes, auth modes and billing, and support on Windows, Linux and macOS | Defines the adapters. These are leads to verify, not facts: I only checked `claude` |
| R-3 | LAN message transports for a handful of machines: NATS with JetStream, MQTT, ZeroMQ, Redis Streams, plain HTTP with SSE or WebSocket, a git-backed queue. Compare by single-binary install on all three OSes, offline delivery, auth, discovery (mDNS), and operations cost | The human's "build our own client if needed" depends on what's available off the shelf |
| R-4 | Existing open-source agent fleet or multi-machine orchestration projects, and how they handle task routing, result return, and trust between nodes | Prior art, per `pre-build-research.md` |
| R-5 | Running a long-lived client per OS: Windows service or scheduled task with desktop access, systemd user service, launchd agent. Include how each gives a desktop session to GUI tests | The Windows OpenSSH limit above shows this decides what can run unattended |
| R-6 | Moving commits between members without ssh: git daemon, smart HTTP on the LAN, bundles in messages. Compare security and simplicity | Section 3's git model assumed ssh reach |
| R-7 | Security for a LAN agent bus: member identity, mutual TLS or shared keys, what a member may execute for another member, and how to stop a message being used to get around a session's permissions | Requirement 5 widens who can ask a machine to run code |

## 7. Decisions for the human

1. **Build or adopt the transport.** Recommendation after R-3, not before.
2. **Whether ssh stays as a fallback** for setup and recovery when the member client is down.
   I'd keep it, since a bootstrap agent needs some first way in.
3. **What a member may do for another member without the orchestrator,** for example run tests
   only, or also start plan and exec jobs.
4. **Where the template and member client live** (section 5.1).
5. **Agent start authority on members:** the credits stack defaults to `human-only`. The
   2026-11-01 proposal recommended `agent-on-user-chat` for Claude credits runs. The same question
   now applies to every CLI.
6. **Whether a Zorivest gate run on a member counts as H1-2 evidence** (2026-11-01 proposal D-2),
   once `--tree-delta` across machines is proven.

## 8. Unverified or untested

- Nothing has crossed the network to <member host> yet. Every git result above ran between local folders.
- Whether `claude --bg` sessions survive the starting shell closing on Windows, and whether they can
  join Remote Control.
- Zorivest `validate_codebase.py --tree-delta` comparing a run made on another machine.
- av-kit and Zorivest test suites running outside `P:`.
- Any capability of Codex, Cursor `agent` or the Antigravity CLI beyond what the model registry
  records.
- The two proposals and this handoff haven't been peer reviewed. The 2026-10-31 proposal passed
  three Codex rounds, but the human rejected it as too complex.

## 9. Suggested next steps

1. Run R-1 to R-3 first. They decide the shape, and R-4 to R-7 refine it.
2. Write `docs/research/fleet/scope.md` per `pre-build-research.md` step 1, from section 2 above.
3. Draft the plan with `/create-plan`. Keep phases independently useful, as the 2026-11-01
   proposal did: bootstrap template and handshake first, then test tasks, then model jobs, then
   member-to-member requests.
4. Set up <member host> as the first member only after the bootstrap template exists, so the template is
   tested on a real machine.
