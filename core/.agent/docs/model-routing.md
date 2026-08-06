# Model & CLI Routing

> **Purpose.** One canonical answer to "which model/CLI does which task, and why."
> Consolidates the routing rules that were previously scattered across
> `development-lifecycle.md`, `cli-dispatch/SKILL.md` §7b, and `AGENTS.md`
> §Dual-Agent Workflow (those files now reference this doc instead of restating it).
>
> Pair this with [harness-profiles.md](harness-profiles.md): that doc says which
> **harness** you are; this doc says which **model** fills each role.

---

## The routed stack (3 model tiers + external reviewer + 2 execution modes)

Field consensus and this project's toolchain converge on a routed stack — *route the
work to the cheapest tier that can do it well.* Uniform top-tier usage wastes 50–80%;
Sonnet-class models handle 80–90% of coding at near-top quality. The stack is: **three
in-family model tiers** (Coordinator / Builder / Router), **one external reviewer** (a
different vendor), and **two execution modes** (surface-orchestration, isolated-worker)
that describe *how* work runs rather than a distinct model tier.

**`role` (from [harness-profiles.md](harness-profiles.md)) → tier mapping:**
`primary-driver` → Coordinator (**harness-conditional:** Cursor default
`cursor-grok-4.5-high-fast`; Claude Code **Opus 5**) + Builder (**harness-conditional:**
Cursor `{composer-2.5-fast|cursor-grok-4.5-high-fast}`; Claude Code **Sonnet 5**,
delegated); `reviewer` → external reviewer; `surface-orchestrator` → surface-orchestration
mode (Gemini 3.5); `isolated-worker` → isolated-worker mode (`claude -p`); `host` → no
model tier (contributes gate/injection constraints only). The Router tier (Haiku 4.5) is a
delegation target the Coordinator spawns, not a harness role.

| Tier | Task class | Executor | Why |
|---|---|---|---|
| **Coordinator** | Orchestration, planning, architecture, synthesis, governance-doc edits, correctness-critical reasoning, troubleshooting, deep-infra | **Harness-conditional:** Cursor default **`cursor-grok-4.5-high-fast`**; Claude Code **Opus 5** (primary-driver session, high/xhigh effort) | Holds the dependency graph; makes the judgment calls |
| **Builder** | Bulk implementation, mechanical edits, test scaffolding, file/log audits, doc sweeps, CI-log reading | **Harness-conditional:** Cursor `{composer-2.5-fast\|cursor-grok-4.5-high-fast}`; Claude Code **Sonnet 5** subagent (low/medium effort) | Near-coordinator quality on the majority of coding; cheaper bulk path on Claude Code |
| **Router** | High-volume classification, triage, grep-collation, inventory, routing decisions | **Haiku 4.5** subagent | Cheapest/fastest — *not* for real logic or multi-file reasoning |
| **Reviewer** (independent) | Adversarial plan & code review | **External CLI** — see the review chain below | Cross-vendor diversity catches failure modes the author's model shares; also offloads tokens off the Claude budget |
| **Surface orchestrator** | Low-reasoning, low-awareness surface work (simple edits, boilerplate coordination) | **Gemini 3.5 fast (high)** | Cheap orchestration for work that needs no deep reasoning; **never** troubleshooting or deep-infra |
| **Isolated worker** | Large parallel/independent workstreams, overnight bursts, isolated-context tasks | **`claude -p` headless**, one per git worktree | Each spawn is an isolated main agent (full Task tool, fresh depth budget, no shared context); worktrees prevent file conflicts |

**Canonical models (2026-07):** Cursor coordinator/builder pins
`cursor-grok-4.5-high-fast` / `composer-2.5-fast`; Claude Code Opus 5 / Sonnet 5 /
Haiku 4.5; GPT-5.6-sol (Codex, **validator/reviewer default**); Gemini 3.5 fast (high).
Fable 5 is reserved for very-large single-shot architecture tasks — never a Cursor
orchestrator default and never a `builder_model` pin. These supersede every earlier
version string in the docs (Sonnet 4.6, GPT-5.5, Opus 4.6-as-orchestrator, GPT-5.4
floor).

---

## Independent-reviewer chain (self-review prohibition)

The implementing agent must never author its own `approved` verdict
(`AGENTS.md` §Execution Contract). "Independent" means **separate context + did not
author this code**, with **vendor diversity preferred**. Now that the primary driver
is Claude, the review chain is:

1. **Codex `gpt-5.6-sol`** — primary reviewer. Cross-vendor; read-only sandbox; GPT-5.6
   code review is first-class (reviews a branch/commit, reports prioritized findings,
   never edits the tree). Effort: `medium` routine, `high` for risk-paths/contract
   surfaces.
2. **Gemini 3.5** — secondary reviewer, **surface-level work only** (per the surface-orchestrator
   scope). Do **not** route troubleshooting or deep-infra review to Gemini.
3. **headless `claude -p`, different model, zero shared context** — last-resort fallback
   **only** when Codex is unavailable/rate-limited **and** the work is deep enough that
   Gemini is inappropriate. Flag it explicitly as *same-vendor* review (weaker
   diversity) in the verdict. Never fall back to same-session self-review.

If none of 1–3 is reachable, follow the rate-limit HARD STOP in
[`../skills/cli-dispatch/SKILL.md`](../skills/cli-dispatch/SKILL.md) §Rate-Limit Fallback — do **not** self-review.

---

## Delegation & nesting rules

- **Delegate down, not up.** The harness-conditional coordinator (Cursor
  `cursor-grok-4.5-high-fast` / Claude Code Opus 5) dispatches builder/router
  subagents and the external reviewer; a builder subagent does not promote itself to
  coordinator. For the detailed "which tasks are mechanical (delegate) vs correctness
  (keep on coordinator)" taxonomy, see [`.agent/docs/model-delegation.md`](model-delegation.md).
- **Nesting depth cap = 5.** Claude Code subagents can spawn subagents up to 5 levels
  deep; the depth-5 agent loses the Agent tool. `Opus → Sonnet → Haiku` (2 levels) is
  safe. For **wide or deep parallel fan-out, prefer `claude -p` headless** (resets the
  depth budget, full capabilities) over deep Task nesting.
- **Worktree isolation for parallel writers.** When multiple agents edit files
  concurrently, give each its own git worktree (or headless session per worktree) so
  they behave like independent developers on separate branches.
- **Token accounting.** Delegating bulk/mechanical work to Sonnet/Haiku and review to
  Codex keeps the coordinator's context lean and moves review cost off the Claude
  budget entirely. This is the intended cost pattern — use it by default for
  audits, sweeps, and log reading (as this very refactor did).

---

## Quick decision guide

| If the task is… | Route to… |
|---|---|
| Deciding *what* to build / how to architect it | Coordinator (Cursor `cursor-grok-4.5-high-fast` / Claude Code Opus 5) |
| Troubleshooting, race conditions, deep-infra, correctness-critical | Coordinator (same harness defaults) — never Gemini |
| Writing lots of straightforward code / tests to a clear spec | Builder (`composer-2.5-fast` or `cursor-grok-4.5-high-fast` on Cursor; Sonnet 5 on Claude Code) |
| Reading logs, auditing many files, mechanical find-replace across a repo | Builder (same pins as above) |
| Classifying/triaging a big list, pure routing | Haiku 4.5 subagent |
| Reviewing a plan or a diff (independent) | Codex gpt-5.6-sol → Gemini (surface) → claude -p (last resort) |
| Simple surface work you want orchestrated cheaply | Gemini 3.5 |
| Many independent tasks in parallel / overnight | `claude -p` headless, one per worktree |

## CLI Dispatch Decision Table

The orchestrator evaluates routing signals, walks this table top-to-bottom, and dispatches on the first match:

| Row | Condition | Model | Effort | Est. Cost (API) |
|-----|-----------|-------|--------|-----------------|
| **1** | `round >= 2 AND prior_severity IN (low, med) AND loc < 200` | GPT-5.6 Sol | **medium** | $0.80-1.50 |
| **2** | `round >= 2 AND prior_severity IN (high, critical)` | GPT-5.6 Sol | **high** | $1.50-3 |
| **3** | `round >= 2 AND prior_severity IN (low, med) AND loc >= 200` | GPT-5.6 Sol | **high** | $1.50-3 |
| **4** | `task == validation_scriptable` | **(no LLM — script)** | N/A | **$0** |
| **5** | `task == validation_checklist AND NOT risk_path` | GPT-5.6 Luna | **medium** | $0.20-0.75 |
| **6** | `task == validation_checklist AND risk_path` | GPT-5.6 Sol | **high** | $2-4 |
| **7** | `task == plan_review AND contract_surfaces == 0 AND loc < 200 AND files < 5` | GPT-5.6 Sol | **medium** | $0.80-1.50 |
| **8** | `task == plan_review AND (contract_surfaces >= 1 OR loc >= 200 OR files >= 5)` | GPT-5.6 Sol | **high** | $2-4 |
| **9** | `task == exec_review AND contract_surfaces == 0 AND loc < 300 AND scope != cross-pkg` | GPT-5.6 Sol | **medium** | $0.80-1.50 |
| **10** | `task == exec_review AND (contract_surfaces >= 1 OR loc >= 300 OR scope == cross-pkg)` | GPT-5.6 Sol | **high** | $2-4 |
| **11** | `task == creative` | Opus 4.5 | **medium** | $1-3 |
| **12** | `task == decision AND risk == high` | Opus 5 | **max** | $3-10 |
| **0** | *(default — catch-all / no other row matches)* | GPT-5.6 Sol | **high** | $2-4 |
