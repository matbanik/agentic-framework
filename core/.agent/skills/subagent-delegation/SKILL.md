---
name: subagent-delegation
description: In-harness subagent detection + delegation gate for Cursor (.cursor/agents/) and Claude Code (.claude/agents/). Resolves fresh_worker from the harness profile, decides which task rows may be delegated to {{PROJECT_NAME}}-builder/{{PROJECT_NAME}}-verifier, and feeds outcomes back into the reflection loop. Load during PLANNING; consult before each task.md row in EXECUTION.
applies_to: [.agent/workflows, docs/execution/plans, task execution]
---

# Subagent Delegation

Both current harnesses ship a native subagent mechanism whose whole point is a **fresh,
isolated context window** for a delegated unit of work — a mechanism counts for *autonomous*
delegation where the **assistant** can address it from its own tool surface:

- **Cursor** — assistant-addressable `Task` tool subtypes `{{PROJECT_NAME}}-builder` /
  `{{PROJECT_NAME}}-verifier` + custom agents in `.cursor/agents/` (own context window, `model:`
  routing, `readonly`, background). Autonomous `fresh_worker` resolves via that Task route.
  Cursor also reads `.claude/agents/`, with `.cursor/` winning name conflicts.
- **Claude Code** — the Agent/Task tool + custom subagents in `.claude/agents/`
  (`model: sonnet|opus|haiku|inherit|<id>`, a `tools` allowlist, `skills:` preload, `memory`). <!-- model-slug-ok: Claude Code `.claude/agents/` frontmatter schema tier aliases (harness_id), not live routing pins -->

This skill is how the orchestrator turns the execution framework's existing delegation
contract (`task.md` `Owner`/`depends_on`/`context_strategy` columns + the
`harness-profiles.md` `fresh_worker` flag) into concrete dispatches — **without** ever
delegating a decision that must stay with the coordinator or the external reviewer.

> The delegation *design* is intentionally simple (two subagents, one decision table,
> sequential foreground dispatch). Improve it through the reflection loop, not by widening
> scope mid-session.

---

## §Harness & Subagent Detection

**Resolve the driver with the `harness-profiles.md` resolution algorithm only** — never from
repository directory presence. This project deliberately creates *both* `.cursor/agents/` and
`.claude/agents/`, so "which agents dir exists" is meaningless as a signal.

Resolution order (identical to `.agent/docs/harness-profiles.md` §How to resolve your profile):

1. **Explicit override** — `{{PROJECT_NAME_UPPER}}_HARNESS_PROFILE` env var or `.agent/context/harness.local.md`.
2. **Driver identity** — the agent's own harness identity string maps to a profile row.
3. **Host merge** — merge the host layer per-flag (conservatively) if embedded.
4. **No match → `UNKNOWN`** — fail safe: `fresh_worker: none`.

Then resolve `fresh_worker` **from the active, authorized tool surface of the resolved driver**,
not from a product name and not from directory presence:

| Resolved driver | Authorized autonomous mechanism | Agent dir | Model economy |
|---|---|---|---|
| Cursor (`Task` tool authorized) | Assistant-addressable Cursor `Task` tool (`{{PROJECT_NAME}}-builder` / `{{PROJECT_NAME}}-verifier`) | `.cursor/agents/` | `builder` (proven); `coordinator` — resolve per harness in the live registry home (see `.agent/INSTANTIATE.md`) |
| Claude Code (Agent/Task tool authorized) | Agent/Task tool (assistant-addressable) | `.claude/agents/` | `builder` class |
| Anything else / no authorized tool | **`none`** | — | every `isolated` row degrades to `compact_continue` |

> **Directory presence is explicitly NOT a detection signal** — it is never valid to infer the
> driver from whether `.cursor/agents/` or `.claude/agents/` exists on disk. **Metadata is never
> permission to spawn:** an `isolated` `context_strategy` only authorizes a fresh worker when a
> concrete authorized mechanism resolved above; otherwise it runs as `compact_continue` inline.

> **Cursor route (demonstrated 2026-07-21).** The assistant's `Task` tool exposes
> `{{PROJECT_NAME}}-builder` and `{{PROJECT_NAME}}-verifier` as assistant-addressable subtypes; orchestrator-originated
> dispatch uses that route + `.cursor/agents/`. Proven builder class: `builder`
> (see `verification-log.md`). Verify the session's `Task` tool still lists the `{{PROJECT_NAME}}-*`
> types at session start. Claude Code remains Agent/Task + `.claude/agents/` when that driver
> is resolved — this section does not claim a Claude Code live probe.

---

## §Delegation Decision Table

Walk this per `task.md` row; **first match wins**:

| Row signals | Decision |
|---|---|
| **No resolved `fresh_worker`** for the driver (per §Detection) | **Never delegate** — every row runs inline (`compact_continue`); metadata is not permission to spawn |
| `context_strategy: isolated` + a resolved `fresh_worker` + a `delegate_to:` annotation in the Task cell | Delegate to the named subagent |
| `Owner: coder` + mechanical class (`model-delegation.md`) + self-contained spec **and a resolved `fresh_worker`** | Delegate to `{{PROJECT_NAME}}-builder`, foreground |
| `Owner: tester`, or any validation whose receipt is long/verbose, **and a resolved `fresh_worker`** | Delegate to `{{PROJECT_NAME}}-verifier` (readonly) |
| **Correctness class**, cross-row reasoning, or an unresolved spec gap | **Never delegate** — keep inline on the coordinator |
| **Review verdict authorship** (plan/execution critical review) | **Never delegate** — external Codex chain only (self-review prohibition) |
| **Commit / push** or any irreversible git action | **Never delegate** — human-approval gate |
| A **human-approval gate** of any kind | **Never delegate** — subagent output is never `USER_EXPLICIT` |
| Dispatch prompt would cost more than the work itself (Cursor startup overhead) | Keep inline |

> **The `fresh_worker` gate is first-match and absolute.** Cursor resolves autonomous
> `fresh_worker` via the assistant-addressable `Task` tool (§Detection), so mechanical/tester
> rows may dispatch when that mechanism is present. Without a resolved mechanism on any driver,
> every row takes the first table row and runs inline.

The four **never-delegate categories** — the correctness class, review verdict authorship,
commit/push, and any human-approval gate — are absolute. A subagent may *do mechanical work* and
*run verification*, but it may never author a verdict, satisfy a decision gate, or perform an
irreversible action.

---

## §Dispatch Prompt Contract

Subagents start with a **clean context**, so the dispatch prompt is the only guaranteed channel
(Cursor confirms only tool/MCP inheritance; Claude Code loads `CLAUDE.md` but the follow-through
is not guaranteed). Every dispatch MUST include:

1. The `task.md` row **verbatim**.
2. The relevant FIC **acceptance criteria**.
3. **Explicit file paths** to read/edit.
4. The **exact validation command** (with the P0 `{{RECEIPTS_DIR}}/` redirect form).
5. The **durable-output path** the row names.
6. The **inline guardrail block** (the AC-4 non-negotiables — redirect pattern, never commit/push,
   test-assertion immutability, no TODO/placeholder, report the receipt path).

---

## §Result Acceptance

**A subagent summary is a *claim*, not evidence.** Before flipping a row `[ ]` → `[x]`, the
orchestrator MUST:

1. Confirm the named **durable output exists on disk** (the row's `durable_outputs` path).
2. Re-run the row's validation command (or read its receipt) and confirm the exit code / counts.
3. Only then mark `[x]`, citing the on-disk artifact — never the subagent's prose.

An on-disk durable output is the precondition for `[x]`; a persuasive summary without it is not.

---

## §Token Economy

- Delegate **context-heavy, verbose, or mechanical** work so its output lands in the subagent's
  own context, not the coordinator's.
- Keep **small tasks inline** — the dispatch prompt plus startup overhead can exceed the work.
- On Cursor, use the **`builder` class** (resolve per harness) for
  builder-class dispatches; on Claude Code use the `builder` class.
- Parallel subagents **multiply** token spend (Cursor docs) and this project runs them
  **sequentially, foreground**. In-harness subagents primarily **protect the coordinator's
  context** rather than guarantee net-token reduction (consistent with `cli-dispatch/SKILL.md`
  §Codex Subagents).

---

## §Guardrails

Subagents **never**:

- **Commit or push**, or perform any irreversible git / data-destructive action (human-approval gate).
- **Author a review verdict** — plan/execution critical review stays on the external Codex chain
  (self-review prohibition, `AGENTS.md` §Execution Contract).
- **Satisfy a human-approval gate** — subagent output is agent-generated, never `USER_EXPLICIT`
  (`GUARDRAILS.md` SIGN 3 provenance).
- **Spawn parallel writers** into the same working tree (worktree isolation rule,
  `.agent/docs/model-routing.md`).
- **Modify a test's assertions** to make it pass, or leave `TODO`/`FIXME`/placeholder stubs.

Every subagent body inlines these non-negotiables as cross-harness defense in depth, because rule
inheritance is not guaranteed on either harness.

---

## §Reflection Loop

The session reflection's **Workflow Signal Log** answers the delegation question: *which rows were
delegated, to which subagent (harness + model), and did any delegated result need rework?*
Rework/friction findings become **Next Session Design Rules** that tune (a) this decision table and
(b) the subagents' `description` fields — Cursor's documented mechanism for steering when a
subagent is auto-selected. The heuristics improve over sessions; the never-delegate categories do not.

---

## §Agent-Discovery Lifecycle

Newly created agent definitions may not be discoverable within the session that created them:

- **Claude Code** — the *first* `agents/` directory created after a session starts is not
  discovered until a **session restart** (Agent SDK watcher note).
- **Cursor** — `.cursor/agents/` is not created by default and newly added files may need a
  **session reload** before `/name` resolves.

Therefore the live smoke/probe (WP-6) runs **only after a discovery checkpoint** (durable-state
save → session restart). Classify the block by its true cause:

- If the harness simply has not **discovered** the newly-added files yet (they exist but need a
  reload), that is a **session/discovery gate**.
- If the assistant's tool surface has **no authorized addressable route** to the custom agent
  (resolved `fresh_worker: none`), that is a **missing-capability block, reason class (b)** —
  it requires the pasted command + error receipt, and a mere session reload will NOT resolve it.

Either way, record a `[B]` with a **linked follow-up** and a **named resume point** whose probe
exercises the **same orchestrator-originated dispatch route** the delegation will use in execution
(not merely a user-launched `/name` invocation, which proves discovery but not autonomous
delegation). An undiscovered/unaddressable agent is **never a silent pass**, and a `[B]` never
counts as AC satisfaction — the criterion is met only by a passing live probe.
