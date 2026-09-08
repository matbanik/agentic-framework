# Model & CLI Routing

> **Purpose.** One canonical answer to "which **capability class** does which task,
> and why." Consolidates the routing rules that were previously scattered across
> `development-lifecycle.md`, `cli-dispatch/SKILL.md` §7b, and `AGENTS.md`
> §Dual-Agent Workflow (those files now reference this doc instead of restating it).
>
> **This doc names classes, never model snapshots.** Which snapshot a class resolves
> to — and what it costs — lives in the **live registry home you instantiate**, not
> in this package. Copy the package-root `.agent/` template and fill it per
> [`INSTANTIATE.md`](../../../.agent/INSTANTIATE.md). Ask the resolver rather than
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
> python <registry-home>/tools/resolve_model.py resolve builder --harness cursor-task --project <project-root>
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
> [`.agent/docs/model-classes.md`](../../../.agent/docs/model-classes.md) for the
> twelve global class contracts.

---

## The routed stack (3 model tiers + external reviewer + 2 execution modes)

Field consensus and this project's toolchain converge on a routed stack — *route the
work to the cheapest tier that can do it well.* Uniform top-tier usage wastes 50–80%;
builder-class models handle 80–90% of coding at near-top quality. The stack is: **three
in-family model tiers** (`coordinator` / `builder` / `router`), **one external reviewer**
(a different vendor), and **two execution modes** (surface-orchestration, isolated-worker)
that describe *how* work runs rather than a distinct model tier.

**`role` (from [harness-profiles.md](harness-profiles.md)) → class mapping:**
`primary-driver` → `coordinator` + `builder` (delegated); `reviewer` →
`independent_reviewer`; `surface-orchestrator` → `surface_orchestrator`;
`isolated-worker` → `isolated_worker`; `host` → no class (contributes
gate/injection constraints only). The `router` class is a delegation target the
coordinator spawns, not a harness role.

Each class resolves per harness, which is how one name covers both a Cursor session
and a Claude Code session without either being written down here.

| Tier | Task class | Class | Why |
|---|---|---|---|
| **Coordinator** | Orchestration, planning, architecture, synthesis, governance-doc edits, correctness-critical reasoning, troubleshooting, deep-infra | `coordinator` | Holds the dependency graph; makes the judgment calls |
| **Builder** | Bulk implementation, mechanical edits, test scaffolding, file/log audits, doc sweeps, CI-log reading | `builder` (and `verifier`, which extends it for read-only validation) | Near-coordinator quality on the majority of coding, at a lower band |
| **Router** | High-volume classification, triage, grep-collation, inventory, routing decisions | `router` | Cheapest/fastest — *not* for real logic or multi-file reasoning |
| **Reviewer** (independent) | Adversarial plan & code review | `independent_reviewer` — see the review chain below | Cross-vendor diversity catches failure modes the author's model shares; also offloads tokens off the primary budget |
| **Cheap validator** | Checklist-shaped validation with no risk path | `checklist_validator` | A distinct, deliberately cheap route; not a discount reviewer (see Decision Table row 5) |
| **Surface orchestrator** | Low-reasoning, low-awareness surface work (simple edits, boilerplate coordination) | `surface_orchestrator` | Cheap orchestration for work that needs no deep reasoning; **never** troubleshooting or deep-infra |
| **Isolated worker** | Large parallel/independent workstreams, overnight bursts, isolated-context tasks | `isolated_worker`, one per git worktree | Each spawn is an isolated main agent with fresh context; worktrees prevent file conflicts. Prefer in-harness Cursor `Task` when available; use the Cursor Agent CLI (`tools/Invoke-CursorAgentDispatch.ps1`) when Task is unavailable / CI / overnight. **Not** an independent-reviewer substitute. |
| **Single-shot architecture** | Very large one-shot architecture reasoning | `architecture_single_shot` | Reserved for that shape only — never a coordinator default and never a `builder_model` pin |
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
either fake diversity or reject a valid reviewer.

The chain, in order:

1. **`independent_reviewer`** — primary. Cross-vendor; read-only sandbox; code review
   is first-class (reviews a branch/commit, reports prioritized findings, never edits
   the tree). Effort: the class's `effort_default` for routine work, one tier up for
   risk-paths and contract surfaces, never above the snapshot's declared
   `effort_ceiling_effective`.
2. **`surface_orchestrator`** — secondary reviewer, **surface-level work only** (per
   that class's declared caveats). Do **not** route troubleshooting or deep-infra
   review to it.
3. **A human.** There is no third machine rung. When rungs 1–2 are unavailable or
   rate-limited, escalate to the human-handoff path in `cli-dispatch/SKILL.md` §0.

> **Same-vendor review is PROHIBITED (2026-09-07).** The former rung 3 — an
> `isolated_worker` on the coordinator's own vendor with zero shared context, "flagged as
> same-vendor" — is **removed**, not deprioritized. Two reasons it had to go rather than
> stay as a labelled-weaker option: a rung that exists gets taken under deadline, and the
> flag lands in a verdict nobody re-reads; and "zero shared context" answers the *context*
> half of independence while quietly conceding the *vendor* half, which is the half that
> catches a whole model family's shared blind spots. Escalating to a human is a real
> terminal state; a self-review round is an artifact that says `approved` without one.

The class's declared `fallbacks` are the rate-limit rungs within rung 1. They are
reported by the resolver but never auto-selected, so a receipt always says which
snapshot actually answered.

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
  (`AGENTS.md` §Session Discipline) governs: do **not** drop a review effort tier to
  recover a price delta.
- **Guard the context cliff.** One snapshot reprices the *entire* request above its
  input boundary — not just the overflow tokens. Large multi-handoff review dispatches
  are the realistic way to cross it, so the resolver raises `split_the_review` when a
  declared `--input-tokens` would straddle it. Split the review rather than straddle.
- **Read the receipt before diagnosing a rate limit.** A snapshot's declared caveats
  include safeguards that can terminate a long agent task mid-run. That surfaces as a
  dispatch with no terminal `turn.completed` event, which `Invoke-CodexDispatch.ps1`
  already treats as a failure.

If none of rungs 1–3 is reachable, follow the rate-limit HARD STOP in
[`../skills/cli-dispatch/SKILL.md`](../skills/cli-dispatch/SKILL.md) §Rate-Limit
Fallback — do **not** self-review.

---

## Delegation & nesting rules

- **Delegate down, not up.** `coordinator` dispatches `builder` / `router` subagents
  and the `independent_reviewer`; a builder subagent does not promote itself to
  coordinator. For the detailed "which tasks are mechanical (delegate) vs correctness
  (keep on coordinator)" taxonomy, see [`.agent/docs/model-delegation.md`](model-delegation.md).
- **Nesting depth cap = 5.** Claude Code subagents can spawn subagents up to 5 levels
  deep; the depth-5 agent loses the Agent tool. `coordinator → builder → router`
  (2 levels) is safe. For **wide or deep parallel fan-out, prefer `isolated_worker`
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
| Troubleshooting, race conditions, deep-infra, correctness-critical | `coordinator` — never `surface_orchestrator` |
| Writing lots of straightforward code / tests to a clear spec | `builder` |
| Reading logs, auditing many files, mechanical find-replace across a repo | `builder` |
| Running a row's validation command and reporting counts, touching nothing | `verifier` |
| Classifying/triaging a big list, pure routing | `router` |
| Reviewing a plan or a diff (independent) | `independent_reviewer` → `surface_orchestrator` (surface) → **a human**; see §Independent-reviewer chain — this row is a summary of it, never a variant |
| Simple surface work you want orchestrated cheaply | `surface_orchestrator` |
| Many independent tasks in parallel / overnight | `isolated_worker`, one per worktree; prefer in-harness Cursor `Task`, else the Cursor Agent CLI |
| Very large single-shot architecture reasoning | `architecture_single_shot` |
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
