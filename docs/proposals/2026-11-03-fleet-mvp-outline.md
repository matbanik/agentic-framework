# Fleet MVP: work order and decisions

Status: outline, 2026-11-03. Nothing is installed or committed. It feeds `/create-plan`.

Rulings: D-1, D-2 and D-3 accepted as recommended, USER_EXPLICIT 2026-11-03: "All 3 recommendations
are accepted, proceed with create plan". Refinements made while planning are in the Decision Log of
`docs/execution/plans/2026-11-03-fleet-mvp/implementation-plan.md`, and where they differ, the plan holds.

Inputs: Mat's 2026-11-03 brief (handoff §2) and its rule that simplicity comes first.
`2026-10-31-fleet-nodes.md`, `2026-11-01-remote-hosts.md` and handoff §5 are **reference only**:
where this outline and they disagree, this outline holds. The HDP receipts are in
`C:/Temp/agentic-framework/fleet-hdp/`.

## 1. The MVP in one paragraph

SUPER runs a small **hub**: one Python file with an HTTP endpoint and a SQLite file. Each member
runs the **same file** in member mode, in a terminal at its own console. The member polls the hub
for tasks, runs them, and posts the result back. Members never accept connections, so they need no
ssh and no inbound firewall rule. Code moves as **git bundles** attached to tasks and results. An
agent on the member, following a **bootstrap template**, sets the machine up and finishes with a
handshake. Agent work uses each CLI's **headless mode** (`claude -p`, `codex exec`, `agent -p`,
`agy -p`), one run per task.

## 2. Get these right now, so later phases don't need a rebuild

These eight points are the long-term design. Each phase adds to them and none replaces them.

1. **Star topology.** Every message goes through the hub. "Member asks member" is a task addressed
   to another member, not a new channel.
2. **Members only pull.** Members make only outbound HTTP requests. The same shape as GitHub's
   self-hosted runners and Buildkite agents: no inbound ports, and polling simply resumes after a
   network drop.
3. **One versioned envelope**, with task states named as in A2A: `submitted`, `working`,
   `input-required`, `completed`, `failed`, `canceled`, `rejected`. It keeps A2A's Task, Message
   and Artifact split. Fields: `v`, `id`, `task_id`, `from`, `to`, `kind`, `created`, `body`,
   `refs` (commit, tree, blob ids), `reply_to`, `requires_human`, `start_quote`. If an A2A gateway
   or a broker such as NATS replaces the HTTP later, the envelope stays.
4. **A closed list of task kinds, one executor for each:** `ping`, `run` and `agent`. Behind
   `agent`, each CLI has an adapter: a command template plus an output parser.
5. **Git moves only as bundles plus commit ids.** No member has `origin`, GitHub credentials or a
   signing key. Landing stays on SUPER, on Mat's word, as in the 2026-11-01 proposal §4.
6. **Authority is in the protocol from day 1.** The hub refuses any task kind its sender may not
   send. No message ever authorizes a commit, push, merge, tag or release. No secret goes in a
   message.
7. **The hub's store is append-only.** A status change is a new row, so the audit trail comes
   free.
8. **No `P:` anywhere.** Paths come from config. A member's home is `~/.agent`, which is rung 3 of
   `.agent/INSTANTIATE.md`.

## 3. Work order

Each phase is useful on its own, and work can stop after any of them. **The MVP is P1 to P3.**

| # | Phase | Builds | Done when | Blocked by |
|---|---|---|---|---|
| P0 | Decide and scope | `docs/research/fleet/scope.md`. Read the Dobby, Sidefleet and agichan sources as reference implementations (§6) | Mat rules D-1. D-2 and D-3 can wait | — |
| P1 | Walking skeleton, SUPER only | `fleet.py` with `hub`, `member`, `send`, `status` and `wait`. The envelope, the SQLite store, and the `ping` task | `fleet send local ping` returns the member's tool versions over localhost | D-1 |
| P2 | Bootstrap template and the first real member | Common template (Windows section filled; Linux and macOS sections only headed). Pairing. Hub TLS. One named firewall rule on SUPER | DUPER's agent sets DUPER up from the template, Mat does the human-only steps, and SUPER's `fleet status` lists DUPER with its capability report | P1 |
| P3 | `run` tasks on av-kit | av-kit's per-project manifest; one slot per project on the member; a snapshot bundle from SUPER that includes untracked files (2026-11-01 §5); results returned | A SUPER session runs av-kit's checks on its uncommitted tree on DUPER and gets the exit code, the log and the tree id back | P2 |
| P4 | `agent` tasks: Claude and Codex | Two adapters; the brief goes in, and the final message, usage and a result bundle come back; landing on SUPER through the existing human-gated path | One plan job runs on DUPER through each CLI, and its result lands on Mat's word | P3, D-2 |
| P5 | Cursor and Antigravity adapters, follow-ups, Zorivest | `stop`, plus `query` and `info` delivered as a resume turn; Zorivest's manifest; 2026-11-01 D-2 (H1-2 evidence) decided here | Each of the four CLIs runs a job. A follow-up gets an answer | P4 |
| P6 | Member-to-member requests | Addressing by capability (for example `to: any{os: macos}`); the hub's allowlist per sender | A member asks for a build on another member and gets the result. SUPER's log shows both | P5, D-3, R-7 |
| P7 | Autostart, Linux and macOS members | A Task Scheduler task at logon, a systemd user service, a launchd agent | A member restarts and rejoins without help | First non-Windows host, R-5 |

**Why this order.** `run` comes before `agent` because it needs no billing or permission decision
and it tests slots and bundles with deterministic commands. It also delivers the first real value:
heavy gates run off SUPER. av-kit comes first because its tests carry no H1-2 evidence question.

**Deliberately left out of the MVP:** discovery (the hub address is in config), message injection
into a live session, the MCP pull tool, NATS, a capability matcher, autostart, Linux and macOS, and
credits (API-key) billing. Each has a phase above or waits until it's needed.

### What each MVP phase should not grow into

- **P1:** one file and the standard library only. Short polling (5 s) instead of long polling or
  server-sent events. No web dashboard.
- **P2:** The template is agent-readable markdown plus a checklist of the steps where the agent
  stops for a human. It's not an installer script. The human-only steps are installing one agent
  CLI and signing in, typing the member key at the console (the agent never sees it), and
  confirming the hub's fingerprint (trust on first use, as ssh does with host keys).
- **P3:** Slots are plain clones with a detached HEAD, not worktrees. av-kit's "no branches or
  worktrees" rule (`P:/av-kit/AGENTS.md:102`) then needs no exception. A result commit sits under
  `refs/fleet/<task>`, which isn't a branch.

## 4. Research: what's still needed

The handoff's seven deep-research prompts (R-1 to R-7) aren't needed before the MVP. The HDP pass
below answered the questions that block the MVP. The rest move to the phase that needs them:

| Item | Status |
|---|---|
| R-1 protocols | Answered enough. A2A is the agent-to-agent standard, now under the Linux Foundation, and gives us the envelope's names. Zed's ACP is editor-to-agent, and Codex and Claude reach it only through adapters, so it isn't the fleet transport |
| R-2 CLI headless modes | Checked against the CLIs installed on SUPER (§6). Resume and permission behaviour get tested in P4 and P5 |
| R-3 transports | Answered by prior art. Settled by D-1 |
| R-4 prior art | Found five projects (§6). Read them in P0 under `pre-build-research.md` instead of a deep-research run |
| R-5 autostart per OS | P7 |
| R-6 moving commits | Answered: bundles (A-3) |
| R-7 bus security | Before P6. Until then only the orchestrator can start work |

## 5. Decisions

### D-1: Build a minimal hub on SUPER that members poll   [one-way-door] [planning]

**Recommendation: build it.** It's one standard-library Python file: an HTTP endpoint over a
SQLite file, TLS with a self-signed certificate that members pin, and one key per member. It is
the smallest thing that meets Mat's brief. Polling members get offline delivery for free, because
the hub holds a task until it's collected. Dobby and Sidefleet show the same hub-and-spoke shape
working with Claude and Codex, and keeping the envelope transport-neutral (§2.3) leaves NATS or
A2A open for later.

**Why not the others**

| Option | Pros (vs. recommendation) | Cons (vs. recommendation) | Sources |
|---|---|---|---|
| ✅ Minimal hub, members poll | — | — | Zorivest MCP HTTP plan `:56`; GitHub runner docs; Dobby |
| ⚠️ Adopt Dobby (MIT, Python, SQLite, polling spokes) | Already has a dashboard, cost accounting and a queue | Claude and Codex only. Version 0.2 from one author, and Windows support isn't stated. Carrying our authority rules (no commit, start quote) means forking it anyway. Better as a reference | pypi.org/project/dobby-orchestrator |
| ⚠️ NATS JetStream broker plus our own client | Real pub/sub, durable queues, request-reply, one binary on every OS | One more server to install and secure. A client library on every member. We'd still write the client and the envelope. Nothing gained at 2 to 5 machines | docs.nats.io; synadia.com |
| ❌ ssh from SUPER (the 2026-11-01 design) | No server code | An ssh server and an inbound rule on every member. Windows OpenSSH ends processes when the session closes. SUPER drives the member, the reverse of the 11-03 model | Win32-OpenSSH #1195 |

**Precedent:** `P:/zorivest/docs/execution/plans/2026-07-28-mcp-http-transport/implementation-plan.md:56`.
That's `USER_EXPLICIT` 2026-07-28, "port 8766 + configurable · per-request auth": stateless HTTP
with a key checked on every request, the same kind of decision, approved. The 2026-11-01
proposal's ssh design was written by an agent and is superseded by the 11-03 brief.
**Research:** Tavily and Exa via Pomera.
- GitHub docs and hostiserver: runners only poll outbound, need no inbound ports and carry on
  after a dropped connection.
- Dobby: a hub on SQLite in WAL mode; spokes register, send heartbeats and long-poll.
- Sidefleet: workers make only outbound calls to the control plane.
- NATS docs: one binary, but persistence needs JetStream.
- Hosted AO: pairing with a self-signed certificate pinned by its fingerprint.

**Reversibility and risk:** The transport is a two-way door if the envelope stays neutral. The
envelope is the part that's hard to change. Plain HTTP would be simpler, but DUPER is on Wi-Fi and
the member key would cross the network in clear, so TLS is in from P2. P2 also needs one named,
reversible inbound rule on SUPER, scoped to the LAN, with records before and after (the
`the local network notes` practice). DUPER needs no rule.
**If you don't answer:** The plan is written on the recommendation. P1 runs on localhost only, so
nothing irreversible happens before you rule. The firewall rule in P2 waits for your word.

### D-2: Who may start an agent job on a member, with what permissions and billing   [governance-value] [planning]   mandatory: [M-13, M-14]

**Recommendation:**
- Only the orchestrator's identity may send `agent` tasks. Each task carries your words as
  `start_quote`, the same `agent-on-user-chat` rule you already use for Zorivest credits runs.
- Claude and Codex run with workspace-level permissions inside the slot, not with a full bypass:
  `codex exec --sandbox workspace-write`, and `claude -p` with the project's allowlist.
- Each run uses the member's own login, so it bills to that subscription. Credits (API key) mode
  waits for a declared budget.
- The Cursor and Antigravity CLIs wait until P5. In headless mode they only run unattended with a
  full bypass: `--force` for Cursor; for `agy`, `--dangerously-skip-permissions`, because its print
  mode ignores `permissions.allow`.

**Why not the others**

| Option | Pros (vs. recommendation) | Cons (vs. recommendation) | Sources |
|---|---|---|---|
| ✅ Orchestrator only, your quote, workspace permissions, the member's own login | — | — | Zorivest `p25-ps3` task.md:186 |
| ⚠️ `human-only`: you type each start yourself (the framework default) | No agent can start anything | Every job needs you at a SUPER terminal, so dispatching from chat doesn't work | `core/.agent/credits/config.json:5` |
| ❌ Any member may start jobs, and full bypass everywhere | Simplest unattended runs, and all four CLIs from P4 | Widens who can run code on a machine, so a prompt injection in one agent's output can travel to another | arXiv 2609.22949; agichan README |

**Precedent:**
- Zorivest `docs/execution/plans/2026-10-21-p25-ps3-plan-sizing-basis/task.md:186`: a run started
  `agent-on-user-chat` with your quote.
- The open issue that a start source can't be verified: `P:/zorivest/.agent/context/known-issues.yaml:18355`.
  The hub's append-only log at least records which session sent each quote.

**Research:**
- arXiv 2609.22949: limits on privilege have to be built into the system, not left to prompts.
- agichan: workers act only on tasks from a manager pinned at start, and ignore other members.
- Dobby's safety warning: bypass mode runs arbitrary commands.
- antigravity-cli #548: print mode ignores `permissions.allow` and stalls.

**Reversibility and risk:** Two-way: a config value plus the adapter's flags. If the choice is
wrong, a job either stalls on a denied tool (too tight) or runs with more reach than intended (too
loose).
**If you don't answer:** P1 to P3 have no agent tasks and go ahead. P4 is held.

### D-3: What one member may ask another to do   [governance-value] [planning]   mandatory: [M-14]

**Recommendation: only `run` tasks** (tests and builds), sent through the hub, with the result
returned to the asking member and recorded in SUPER's log. A member never sends an `agent` task.
Until P6, the hub refuses every task a member sends.

| Option | Pros (vs. recommendation) | Cons (vs. recommendation) | Sources |
|---|---|---|---|
| ✅ `run` only, through the hub | — | — | handoff §5.3 |
| ⚠️ `agent` tasks too, relaying your quote | "Plan this on the Mac" works without SUPER | Your words get relayed by an agent, which is hard to audit and carries injection from one agent to the next | arXiv 2609.22949 |
| ❌ Peer-to-peer, direct between members | No dependency on the hub | Inbound ports and a trust setup for every pair of machines, the opposite of §2.1 and §2.2 | — |

**Precedent:** none found for this kind of decision.
**Research:** as for D-2.
**Reversibility and risk:** Two-way: it's an allowlist row in the hub's config.
**If you don't answer:** Nothing changes before P6. The hub ships refusing tasks from members.

### Decided by the agent (HDP §4: the obviousness test passed). Tell me to reverse any of them.

```yaml
decision_log:
  - id: A-1
    stage: planning
    question: "Run the R-1..R-7 deep research before planning?"
    resolution: autonomous
    class: two-way
    mandatory: none
    chosen: "No. P0 does pre-build-research.md at MVP size (scope.md plus the reference repos); R-5 and R-7 move to P7 and P6"
    source_tag: Local Canon
    precedents: ["core/.agent/workflows/pre-build-research.md:11-15 — research order is local canon, primary sources, then reference implementations; no deep-research run is required"]
    research: {engine: tavily, sources: ["the D-1 to D-3 sources answer what blocks the MVP"]}
    reasoning: "Mat's brief puts simplicity first. Questions that don't block the MVP get researched when their phase starts"
  - id: A-2
    stage: planning
    question: "How does a task reach an agent CLI?"
    resolution: autonomous
    class: two-way
    mandatory: none
    chosen: "One headless run per task, started by the member as a child process; follow-ups go in as a resume turn; nothing is injected into a live session; the MCP pull tool waits"
    source_tag: Research-backed
    precedents: ["handoff §5.2 suggested the pull tool first; it was a framing, not a ruling"]
    research:
      engine: native
      sources:
        - "Local --help on SUPER, receipts in fleet-hdp/*-help.txt: claude 2.1.312 has -p, --output-format, --input-format and -r/--resume; codex 0.165.0 has exec --json, -o and exec resume; Cursor agent 2026.10.22 has -p, --output-format, --resume, --force and --trust; agy 1.4.12 has -p, --output-format and --conversation"
        - "dev.to, 'Headless Mode in 5 Agents' — the same headless, JSON and resume pattern in every major CLI"
        - "Dobby and Sidefleet start the CLIs as child processes"
    reasoning: "It works the same way for all four CLIs without per-CLI injection code"
  - id: A-3
    stage: planning
    question: "How do commits move without ssh?"
    resolution: autonomous
    class: two-way
    mandatory: none
    chosen: "Git bundles attached to tasks and results; SUPER fetches a result into a non-branch ref; landing as in 2026-11-01 §4"
    source_tag: Research-backed
    precedents: ["2026-11-01-remote-hosts.md §4-5 — tested: squash landing, merge-tree check, snapshot with a temporary index"]
    research:
      engine: tavily
      sources:
        - "git-scm.com/docs/git-bundle — official way to move objects with no server on the other side"
        - "git-scm.com/book, 'The Protocols' — git daemon has no authentication at all, so it's ruled out for private repos"
        - "Sqwakie, via dev.to — a seat's commits return as a git bundle"
    reasoning: "It reuses the hub's channel and its one authentication setup; nothing new listens on any machine"
  - id: A-4
    stage: planning
    question: "Should ssh stay as a fallback?"
    resolution: autonomous
    class: two-way
    mandatory: none
    chosen: "Not in the MVP. Bootstrap runs at the member's console; recovery is at the console, or through DUPER's existing WinRM. Revisit for a member without a console"
    source_tag: Local Canon
    precedents: ["handoff §2 item 5 — Mat: 'LAN first, possibly without ssh'"]
    research: {engine: none, sources: []}
    reasoning: "The member's own agent does the setup, so nothing needs a remote way in"
  - id: A-5
    stage: planning
    question: "Where do the template, fleet.py and the project manifests live?"
    resolution: autonomous
    class: two-way
    mandatory: none
    chosen: "The common template and fleet.py go in root .agent/fleet/ (the machine-home template; installed to ~/.agent/fleet on members, P:/.agent on SUPER). Each project's manifest lives in that repo at .agent/fleet.yaml, from a template in core/"
    source_tag: Local Canon
    precedents: [".agent/INSTANTIATE.md:1-11 — root .agent/ is the shared-home template; core/.agent/ is the copy each project takes"]
    research: {engine: none, sources: []}
    reasoning: "The repo already divides files into machine-level and project-level; this follows that division"
  - id: A-6
    stage: planning
    question: "How is the hub built?"
    resolution: autonomous
    class: two-way
    mandatory: none
    chosen: "Standard-library Python, one file used in both modes, SQLite, 5 s polling, append-only messages"
    source_tag: Research-backed
    precedents: []
    research: {engine: exa, sources: ["pypi.org/project/dobby-orchestrator — SQLite in WAL mode, spokes polling the hub"]}
    reasoning: "Nothing to install beyond Python, which every member needs anyway"
  - id: A-7
    stage: planning
    question: "How does the member process run on Windows in the MVP?"
    resolution: autonomous
    class: two-way
    mandatory: none
    chosen: "In a foreground terminal in the logged-in session; autostart at logon comes in P7"
    source_tag: Research-backed
    precedents: ["2026-11-01-remote-hosts.md §5 — Electron E2E needs a real desktop"]
    research: {engine: tavily, sources: ["learn.microsoft.com Q&A — a task set to 'run whether user is logged on or not' gets no desktop; Session 0 isolation is by design"]}
    reasoning: "A terminal gives the E2E tests a desktop at no extra cost"
  - id: A-8
    stage: planning
    question: "Phase order, first project and first CLIs"
    resolution: autonomous
    class: two-way
    mandatory: none
    chosen: "run before agent; av-kit first; Claude and Codex first"
    source_tag: Local Canon
    precedents: ["2026-11-01-remote-hosts.md §7 phases — av-kit tests first"]
    research: {engine: none, sources: []}
    reasoning: "Each step needs no decision that the step before it hasn't settled"
open_decisions: [D-1, D-2, D-3]
deferred: ["2026-11-01 D-2, whether a Zorivest gate run on a member counts as H1-2 evidence: decided at P5, when Zorivest's manifest exists"]
```

## 6. Sources and findings

**Corrections to the handoff:**
- §4 says the Antigravity CLI wasn't found. It's installed on SUPER: `agy` 1.4.12 at
  `%LOCALAPPDATA%/agy/bin/agy`.
- §5.2 suggests testing the pull tool first. Headless runs are simpler and work the same way for
  every CLI (A-2).

**Prior art to read in P0:**
- [Dobby](https://pypi.org/project/dobby-orchestrator/): the closest match. A hub on aiohttp and
  SQLite; spokes register, send heartbeats and poll; runs Claude Code and Codex.
- [Sidefleet](https://dev.to/alexcarney/running-coding-agents-on-more-than-one-machine-herdr-agent-of-empires-sidefleet-claude-codes-47kj):
  workers make outbound calls only and run a git worktree per task. macOS and Linux only.
- [agichan](https://github.com/slonana-labs/agichan): the manager's identity is pinned. The
  agent's last line, `STATUS: done` or `blocked`, decides the result, not its exit code. Worth
  copying.
- [Vicoa](https://github.com/vicoa-ai/vicoa) and [Hosted AO](https://github.com/agentlab-in/hosted-ao):
  full stacks, too heavy to adopt. Hosted AO's certificate pinning is the model for P2's TLS.

**Standards and docs:**
- [A2A](https://developers.googleblog.com/en/a2a-a-new-era-of-agent-interoperability) and
  [its artifact concept](https://agent2agent.info/docs/concepts/artifact): Task, Message and
  Artifact; results that must survive a disconnect go in an artifact.
- [ACP agents](https://agentclientprotocol.com/get-started/agents): connects editors to agents;
  Codex and Claude join through adapters.
- [git-bundle](https://git-scm.com/docs/git-bundle) and
  [git's server protocols](https://git-scm.com/book/ms/v2/Git-on-the-Server-The-Protocols).
- [GitHub self-hosted runners](https://docs.github.com/en/actions/reference/runners/self-hosted-runners)
  and [the pull-model write-up](https://www.hostiserver.com/community/articles/self-hosted-cicd-architecture-runners).

**Risks:**
- [Antigravity headless ignores the allowlist](https://github.com/google-antigravity/antigravity-cli/issues/548).
- [Headless Cursor needs `--force` to write files](https://forum.cursor.com/t/background-agent-handoff/157041).
- [Prompt injection between agents](https://arxiv.org/html/2609.22949v1).
