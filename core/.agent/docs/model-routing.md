# Model & CLI Routing

> **Purpose.** One canonical answer to "which **capability class** does which task,
> and why." Consolidates the routing rules that were previously scattered across
> `development-lifecycle.md`, `cli-dispatch/SKILL.md` §7b, and `AGENTS.md`
> §Dual-Agent Workflow (those files now reference this doc instead of restating it).
>
> **This doc names classes, never model snapshots.** Which snapshot a class resolves
> to — and what it costs — lives in the **live registry home you instantiate**, not
> in this package. Copy the package-root `.agent/` template and fill it per
> [`INSTANTIATE.md`](../INSTANTIATE.md). Ask the resolver rather than
> reading a value out of prose:
>
> ```powershell
> Import-Module <registry-home>/tools/ModelRegistry.psm1
> Resolve-AgentModel -Class independent_reviewer -Harness codex-cli -AuthorVendor <vendor> -Project <project-root>
> ```
>
> ```powershell
> # paste-able argv form (prints the bare slug). `$ErrorActionPreference = 'Stop'`
> # is part of the shape: without it a failed resolve leaves `-m` empty and the
> # CLI launches on the account default.
> $ErrorActionPreference = 'Stop'
> -m $(resolve independent_reviewer -AuthorVendor <vendor> -Project <project-root>)
> ```
>
> ```bash
> python <registry-home>/tools/resolve_model.py resolve builder --harness claude-code-agents --project <project-root>
> ```
>
> `-Project` / `--project` names the repo whose overlay governs the answer; without it
> the live registry's global catalog replies and the project's floors, pins and vendor
> rules never apply.
>
> That indirection is the whole point: a model bump is one edit in the live
> registry, and no edit here. A slug written back into this file is a staleness
> bug, and `check_model_slugs.py` fails the quality gate on it.
>
> Pair this with [harness-profiles.md](harness-profiles.md): that doc says which
> **harness** you are; this doc says which **class** fills each role. Pair it with
> the class contracts in the registry home you instantiate (see
> [`INSTANTIATE.md`](../INSTANTIATE.md)).

---

## The routed stack (3 model tiers + external reviewer + isolated-worker mode)

Field consensus and this project's toolchain converge on a routed stack — *route the
work to the cheapest tier that can do it well.* Uniform top-tier usage wastes 50–80%;
builder-class models handle 80–90% of coding at near-top quality. The stack is: **three
in-family model tiers** (`coordinator` / `builder` / `router`), **one external reviewer**
(a different vendor), and **one execution mode** (isolated-worker) that describes *how*
work runs rather than a distinct model tier.

**`role` (from [harness-profiles.md](harness-profiles.md)) → class mapping:**
`primary-driver` → `coordinator` + `builder` (delegated); `reviewer` →
`independent_reviewer`; `isolated-worker` → `isolated_worker`; `host` → no class (contributes
gate/injection constraints only). The `router` class is a delegation target the
coordinator spawns, not a harness role.

Each class resolves per harness, which is how one name covers both a Claude Code
session and a Codex CLI dispatch without either snapshot being written down here.

| Tier | Task class | Class | Why |
|---|---|---|---|
| **Coordinator** | Orchestration, planning, architecture, synthesis, governance-doc edits, correctness-critical reasoning, troubleshooting, deep-infra | `coordinator` | Holds the dependency graph; makes the judgment calls |
| **Builder** | Bulk implementation, mechanical edits, test scaffolding, file/log audits, doc sweeps, CI-log reading | `builder` (and `verifier`, which extends it for read-only validation) | Near-coordinator quality on the majority of coding, at a lower band |
| **Router** | High-volume classification, triage, grep-collation, inventory, routing decisions | `router` | Cheapest/fastest — *not* for real logic or multi-file reasoning |
| **Scout** | Read-only search fan-out: where something lives, which files follow a convention, which call sites use a symbol; returns paths + excerpts | `scout` (extends `router`) | Keeps file dumps out of the coordinator's context at the cheapest tier; never judges correctness, never decides a gate |
| **Peer reviewer** (advisory) | A same-vendor adversarial second read of a correctness-critical diff or plan, before the independent review | `peer_reviewer` | Catches defects before a paid review round. Advisory input only: never writes a verdict file, never authors `approved` — the verdict stays with `independent_reviewer` |
| **Reviewer** (independent) | Adversarial plan & code review | `independent_reviewer` — see the review chain below | Cross-vendor diversity catches failure modes the author's model shares; also offloads tokens off the primary budget |
| **Cheap validator** | Checklist-shaped validation with no risk path | `checklist_validator` | A distinct, deliberately cheap route; not a discount reviewer (see Decision Table row 5) |
| **Isolated worker** | Large parallel/independent workstreams, overnight bursts, isolated-context tasks | `isolated_worker`, one per git worktree | Each spawn is an isolated main agent with fresh context; worktrees prevent file conflicts. Prefer the in-harness Agent tool (`.claude/agents/`) when available; use headless `claude -p` when it is unavailable / CI / overnight. **Not** an independent-reviewer substitute. |
| **Architect** (advisory) | Very large one-shot architecture reasoning | `architect` | Reserved for that shape only, and invoked only on explicit human direction or an accepted grouping row flagged `architecture-risk: yes` — never a coordinator default, never a builder, never a `builder_model` pin, never a verdict |
| **Creative prose** | Prose whose voice matters, and the second reader on it | `creative_prose` | Pinned by *difference*, not recency: see the class's registry note |

Every snapshot the classes above resolve to is recorded once, in the adopter's
registry catalog, together with its vendor, price band, effort ceiling, and caveats.

---

## Independent-reviewer chain (self-review prohibition)

The implementing agent must never author its own `approved` verdict
(`AGENTS.md` §Execution Contract). "Independent" means **separate context + did not
author this code + a different vendor than the author**. Vendor distinctness is a
**requirement, not a preference**: the `independent_reviewer` class declares
`vendor_distinct_from: author`, so the dispatch wrapper requires the authoring agent's
vendor (`-AuthorVendor` / `--author-vendor`) and refuses to guess it — assuming it would
either fake diversity or reject a valid reviewer. Rung 2 below is the single exception,
it is flagged in the verdict, and it is reachable only when rung 1 is not.

The chain, in order:

1. **`independent_reviewer`** — primary. Cross-vendor; read-only sandbox; code review
   is first-class (reviews a branch/commit, reports prioritized findings, never edits
   the tree). Effort: the class's `effort_default` for routine work, one tier up for
   risk-paths and contract surfaces, never above the snapshot's declared
   `effort_ceiling_effective`.
2. **`fallback_reviewer`** — headless `claude -p`, the same-vendor fallback. It runs
   **only** on a rate-limit or unavailability receipt from rung 1, never by preference.
   Four conditions hold every time:
   - **Isolation:** a fresh headless process with zero shared context — never the
     authoring session and never a subagent of it.
   - **Tier floor (policy):** the reviewer's tier is at least the author's. The
     dispatcher applies this rule; the resolver does not. The binding covers authors up
     to its own tier, and a higher-tier author passes `--slug` with that tier's catalog
     id. Never pass `--slug` with a tier below the binding's. The contract checks only
     the vendor and `effort_floor: high`. That floor refuses a snapshot whose effort
     ceiling is below `high`; a smaller-tier snapshot that supports `high` passes it, so
     the floor is not a tier check. The schema has no tier key.
   - **Flag:** the verdict names itself same-vendor review whenever the author shares
     its vendor (`flag_if_same_vendor_as_author: true`).
   - **Return:** rung 1 takes the next round as soon as it answers again.
3. **A human.** A HARD STOP, reached only when both machine rungs are rate-limited or
   unavailable — the human-handoff path in `cli-dispatch/SKILL.md` §0.

> **A same-vendor fallback, not a same-vendor default (2026-10-07).** The 2026-09-07
> prohibition removed this rung for two reasons, and both stay — as conditions rather
> than as a ban. *A rung that exists gets taken under deadline:* so it needs a rung-1
> rate-limit receipt, and a deadline is not one. *"Zero shared context" answers the
> context half of independence and concedes the vendor half:* so the verdict is flagged,
> and once rung 1 recovers it may re-read a flagged `approved` on a risk path
> (advisory). What changed is the terminal state: a human cannot review at agent
> throughput, and in practice the human rung stalled the loop instead of reviewing it.
> Self-review is still forbidden — the authoring session never reviews its own work, at
> any effort.

The class's declared `fallbacks` are the rate-limit rungs within rung 1. They are
reported by the resolver but never auto-selected, so a receipt always says which
snapshot actually answered. A binding may declare none; a rate-limited rung 1 then
goes to rung 2.

### Effort ceilings and cost (Research-backed, 2026-09-04)

These are *rules*; the numbers they refer to live in the registry catalog
(`price_band`, `price_per_mtok`, `price_note`, `effort_ceiling_effective`,
`context.reprices_whole_request_above`, `caveats`). Read them from there — a figure
copied into prose is stale the day the vendor reprices.

- **Never dispatch above a snapshot's `effort_ceiling_effective`.** Where an older
  rule says "always `max`", read it as "the class's ceiling". The resolver clamps
  to the ceiling and reports `effort_clamped`, so a receipt shows when this
  happened rather than hiding it.
- **Respect the effort sets, not a remembered list.** Snapshots differ in which
  effort levels they accept, and the registry records each one's set; a level a
  snapshot has removed is an error, not a silent downgrade.
- **Cost is compared by band, not by dollars.** Classes declare a
  `price_ceiling_band`, and the resolver refuses a snapshot above it. Quality-First
  (`AGENTS.md` §Session and Profile) governs: do **not** drop a review effort tier to
  recover a price delta.
- **Guard the context cliff.** Some snapshots reprice the *entire* request above an
  input boundary — not just the overflow tokens. Large multi-handoff review dispatches
  are the realistic way to cross it, so the resolver raises `split_the_review` when a
  declared `--input-tokens` would straddle it. Split the review rather than straddle.
- **Read the receipt before diagnosing a rate limit.** A snapshot's declared caveats
  include safeguards that can terminate a long agent task mid-run. That surfaces as a
  dispatch with no terminal `turn.completed` event, which `Invoke-CodexDispatch.ps1`
  already treats as a failure.

If neither machine rung is reachable, follow the rate-limit HARD STOP in
[`../skills/cli-dispatch/SKILL.md`](../skills/cli-dispatch/SKILL.md) §Rate-Limit
Fallback — do **not** self-review.

---

## Delegation & nesting rules

- **Delegate down, not up.** `coordinator` dispatches `builder` / `verifier` / `router` /
  `scout` subagents, a `peer_reviewer` for an advisory second read, and the
  `independent_reviewer`; a builder subagent does not promote itself to coordinator. For the detailed "which tasks are mechanical (delegate) vs correctness
  (keep on coordinator)" taxonomy, see [`.agent/docs/model-delegation.md`](model-delegation.md).
- **Nesting depth cap = 3.** Claude Code lets subagents spawn subagents 3 levels below the
  main conversation by default (`CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` changes it); at the
  limit the Agent tool is withheld (Claude Code docs, sub-agents §Spawning, read
  2026-10-07). `coordinator → builder → router` (2 levels) is safe. For **wide or deep parallel fan-out, prefer `isolated_worker`
  on `claude-p`** (resets the depth budget, full capabilities) over deep Task nesting.
- **Worktree isolation for parallel writers.** When multiple agents edit files
  concurrently, give each its own git worktree (or headless session per worktree) so
  they behave like independent developers on separate branches.
- **Token accounting.** Delegating bulk/mechanical work to `builder` / `router` and
  review to `independent_reviewer` keeps the coordinator's context lean and moves
  review cost onto a separate budget. This is the intended cost pattern — use it by
  default for audits, sweeps, and log reading (as this very refactor did).

---

## Quick decision guide

| If the task is… | Route to… |
|---|---|
| Deciding *what* to build / how to architect it | `coordinator` |
| Troubleshooting, race conditions, deep-infra, correctness-critical | `coordinator` |
| Writing lots of straightforward code / tests to a clear spec | `builder` |
| Reading logs, auditing many files, mechanical find-replace across a repo | `builder` |
| Running a row's validation command and reporting counts, touching nothing | `verifier` |
| Classifying/triaging a big list, pure routing | `router` |
| Sweeping many files for one answer (where is X, who calls Y) when only the conclusion is needed | `scout` |
| A second, advisory read of a correctness-critical diff or plan before the independent review | `peer_reviewer` (advisory; the verdict stays with `independent_reviewer`) |
| Reviewing a plan or a diff (independent) | `independent_reviewer` → `fallback_reviewer` (headless `claude -p`, only on a rate-limit receipt, flagged same-vendor) → **a human** (HARD STOP); see §Independent-reviewer chain — this row is a summary of it, never a variant |
| Many independent tasks in parallel / overnight | `isolated_worker`, one per worktree; prefer the in-harness Agent tool, else headless `claude -p` |
| Very large single-shot architecture reasoning | `architect` (only on explicit human direction or a grouping row flagged `architecture-risk: yes`) |
| Prose whose voice matters, or a second reader on prose | `creative_prose` |

## CLI Dispatch Decision Table

The orchestrator evaluates routing signals, walks this table top-to-bottom, and
dispatches on the first match.

Cost is expressed as the class's **price band** (`low` < `medium` < `high` < `xhigh`),
which is what the registry compares against a class's `price_ceiling_band`. Per-token
and per-task figures live in the catalog. Row 5 keeps its own cheap route: the
reviewer's current generation ships no low-band variant, so `checklist_validator`
binds a previous-generation snapshot rather than discounting the reviewer. Which
snapshot that is, and when it changes, is the registry's business.

| Row | Condition | Class | Effort | Band |
|-----|-----------|-------|--------|------|
| **1** | `round >= 2 AND prior_severity IN (low, med) AND loc < 200` | `independent_reviewer` | **medium** | high |
| **2** | `round >= 2 AND prior_severity IN (high, critical)` | `independent_reviewer` | **high** | high |
| **3** | `round >= 2 AND prior_severity IN (low, med) AND loc >= 200` | `independent_reviewer` | **high** | high |
| **4** | `task == validation_scriptable` | **(no LLM — script)** | N/A | **none** |
| **5** | `task == validation_checklist AND NOT risk_path` | `checklist_validator` | **medium** | low |
| **6** | `task == validation_checklist AND risk_path` | `independent_reviewer` | **high** | high |
| **7** | `task == plan_review AND contract_surfaces == 0 AND loc < 200 AND files < 5` | `independent_reviewer` | **medium** | high |
| **8** | `task == plan_review AND (contract_surfaces >= 1 OR loc >= 200 OR files >= 5)` | `independent_reviewer` | **high** | high |
| **9** | `task == exec_review AND contract_surfaces == 0 AND loc < 300 AND scope != cross-pkg` | `independent_reviewer` | **medium** | high |
| **10** | `task == exec_review AND (contract_surfaces >= 1 OR loc >= 300 OR scope == cross-pkg)` | `independent_reviewer` | **high** | high |
| **11** | `task == creative` | `creative_prose` | **medium** | high |
| **12** | `task == decision AND risk == high` | `coordinator` | **ceiling** | xhigh |
| **0** | *(default — catch-all / no other row matches)* | `independent_reviewer` | **high** | high |

Row 12's effort reads **ceiling** rather than a level name: the coordinator class
resolves per harness, and the harnesses it binds to do not share one top effort
level. The resolver returns the right one.
