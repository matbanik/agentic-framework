---
name: subagent-delegation
description: In-harness subagent detection + delegation gate for Claude Code (.claude/agents/). Resolves fresh_worker from the harness profile, decides which task rows may be delegated to {{PROJECT_NAME}}-builder/{{PROJECT_NAME}}-verifier/{{PROJECT_NAME}}-scout/{{PROJECT_NAME}}-peer_reviewer, and feeds outcomes back into the reflection loop. Load during PLANNING; consult before each task.md row in EXECUTION.
applies_to: [.agent/workflows, docs/execution/plans, task execution]
---

# Subagent Delegation

The driving harness ships a native subagent mechanism whose whole point is a **fresh, isolated
context window** for a delegated unit of work. A mechanism counts for *autonomous* delegation only
where the **assistant** can address it from its own tool surface:

- **Claude Code** — the Agent/Task tool + custom subagents in `.claude/agents/`
  (`model: sonnet|opus|haiku|fable|inherit|<id>`, `effort:`, a `tools` allowlist, `skills:` preload, `memory`). <!-- model-slug-ok: Claude Code `.claude/agents/` frontmatter schema tier aliases (harness_id), not live routing pins -->

Cursor is an IDE host only: it carries no agent definitions and resolves no
worker of its own. When Claude Code runs inside Cursor, the Claude Code driver row supplies the
worker.

This skill is how the orchestrator turns the execution framework's existing delegation
contract (`task.md` `Owner`/`depends_on`/`context_strategy` columns + the
`harness-profiles.md` `fresh_worker` flag) into concrete dispatches — **without** ever
delegating a decision that must stay with the coordinator or the external reviewer.

> The delegation *design* is intentionally simple (four subagents, one decision table,
> sequential foreground dispatch). Improve it through the reflection loop, not by widening
> scope mid-session.

---

## §Harness & Subagent Detection

**Resolve the driver with the `harness-profiles.md` resolution algorithm only** — never from
repository directory presence. A `.claude/agents/` directory on disk says nothing about which
harness is reading this file.

Resolution order (identical to `.agent/docs/harness-profiles.md` §How to resolve your profile):

1. **Explicit override** — `{{PROJECT_NAME_UPPER}}_HARNESS_PROFILE` env var or `.agent/context/harness.local.md`.
2. **Driver identity** — the agent's own harness identity string maps to a profile row.
3. **Host merge** — merge the host layer per-flag (conservatively) if embedded.
4. **No match → `UNKNOWN`** — fail safe: `fresh_worker: none`.

Then resolve `fresh_worker` **from the active, authorized tool surface of the resolved driver**,
not from a product name and not from directory presence:

| Resolved driver | Authorized autonomous mechanism | Agent dir | Model economy |
|---|---|---|---|
| Claude Code (Agent/Task tool authorized) | Agent/Task tool (assistant-addressable) | `.claude/agents/` | `builder` / `verifier` / `scout` / `peer_reviewer` classes — resolve per harness in the live registry home (see `.agent/INSTANTIATE.md`) |
| Anything else / no authorized tool | **`none`** | — | every `isolated` row degrades to `compact_continue` |

> **Directory presence is explicitly NOT a detection signal.** **Metadata is never permission to
> spawn:** an `isolated` `context_strategy` only authorizes a fresh worker when a concrete
> authorized mechanism resolved above; otherwise it runs as `compact_continue` inline. Verify at
> session start that the Agent tool lists the `{{PROJECT_NAME}}-*` types; probe evidence lives in
> `verification-log.md`.

### Agent files

| File (`.claude/agents/`) | Class | `effort:` | `tools:` | Use |
|---|---|---|---|---|
| `{{PROJECT_NAME}}-builder.md` | `builder` | `medium` | all | The mechanical class, one `task.md` row per dispatch |
| `{{PROJECT_NAME}}-verifier.md` | `verifier` | `low` | `Read, Bash, Grep, Glob` | Run a row's exact validation command; report counts + the receipt path |
| `{{PROJECT_NAME}}-scout.md` | `scout` | `low` | `Read, Grep, Glob, Bash` | Read-only search fan-out; returns paths + excerpts, never judges |
| `{{PROJECT_NAME}}-peer_reviewer.md` | `peer_reviewer` | `high` | `Read, Grep, Glob, Bash` | Advisory adversarial read of one diff or plan; never writes a verdict file, never authors `approved` |

`model:` is generated from the registry by `resolve_model.py sync` — never hand-edit it. `effort:`
is pinned by hand; keep it equal to the class's `effort_default` in the registry, and add a
test that fails when a pin drifts. The last `-` segment of the file stem names the class, which is why the peer reviewer
file is `{{PROJECT_NAME}}-peer_reviewer.md`. Do not set `CLAUDE_CODE_EFFORT_LEVEL`: it overrides every pin.

---

## §Delegation Decision Table

Walk this per `task.md` row; **first match wins**:

| Row signals | Decision |
|---|---|
| **No resolved `fresh_worker`** for the driver (per §Detection) | **Never delegate** — every row runs inline (`compact_continue`); metadata is not permission to spawn |
| `context_strategy: isolated` + a resolved `fresh_worker` + a `delegate_to:` annotation in the Task cell | Delegate to the named subagent |
| `Owner: coder` + mechanical class (`model-delegation.md`) + self-contained spec **and a resolved `fresh_worker`** | Delegate to `{{PROJECT_NAME}}-builder`, foreground |
| `Owner: tester`, or any validation whose receipt is long/verbose, **and a resolved `fresh_worker`** | Delegate to `{{PROJECT_NAME}}-verifier` (readonly) |
| A search question that needs many files swept and only the conclusion back, **and a resolved `fresh_worker`** | Delegate to `{{PROJECT_NAME}}-scout` (readonly; paths + excerpts) |
| A second read of a correctness-critical diff or plan before the independent review, **and a resolved `fresh_worker`** | Delegate the *read* to `{{PROJECT_NAME}}-peer_reviewer` (readonly, advisory findings only); the work and every decision stay inline, and the verdict row below still applies |
| **Correctness class**, cross-row reasoning, or an unresolved spec gap | **Never delegate** — keep inline on the coordinator |
| **Review verdict authorship** (plan/execution critical review) | **Never delegate** — external Codex chain only (self-review prohibition) |
| **Commit / push** or any irreversible git action | **Never delegate** — human-approval gate |
| A **human-approval gate** of any kind | **Never delegate** — subagent output is never `USER_EXPLICIT` |
| Dispatch prompt would cost more than the work itself (subagent startup overhead) | Keep inline |

> **The `fresh_worker` gate is first-match and absolute.** Without a resolved mechanism, every
> row takes the first table row and runs inline — or, for intentionally headless work, the
> orchestrator may shell out to headless `claude -p` via cli-dispatch instead of inventing a
> worker spawn.

The four **never-delegate categories** — the correctness class, review verdict authorship,
commit/push, and any human-approval gate — are absolute. A subagent may *do mechanical work* and
*run verification*, but it may never author a verdict, satisfy a decision gate, or perform an
irreversible action.

---

## §Dispatch Prompt Contract

Subagents start with a **clean context**, so the dispatch prompt is the only guaranteed channel
(Claude Code loads `CLAUDE.md`, but the follow-through is not guaranteed). Every dispatch MUST
include:

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
- Use the `builder` class for builder dispatches, the `verifier` class for readonly
  validation, and the `scout` class for search fan-out; the `.claude/agents/` `model:` lines are
  generated from the registry, never hand-edited.
- Parallel subagents **multiply** token spend and this project runs them **sequentially,
  foreground**. In-harness subagents primarily **protect the coordinator's context** rather than
  guarantee net-token reduction (consistent with `cli-dispatch/SKILL.md` §Codex Subagents).

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

Every subagent body inlines these non-negotiables as defense in depth, because rule inheritance
is not guaranteed.

---

## §Reflection Loop

The session reflection's **Workflow Signal Log** answers the delegation question: *which rows were
delegated, to which subagent (harness + class), and did any delegated result need rework?*
Rework/friction findings become **Next Session Design Rules** that tune (a) this decision table and
(b) the subagents' `description` fields — the field Claude Code reads when it auto-selects a
subagent. The heuristics improve over sessions; the never-delegate categories do not.

---

## §Agent-Discovery Lifecycle

Claude Code loads agent definitions at session start:

- The *first* `agents/` directory created after a session starts is not discovered until a
  **session restart** (Agent SDK watcher note).
- An edit to an existing definition (for example a registry-driven `model:` rewrite) is not
  picked up by the running session either; the session keeps the definition it loaded.

Therefore the live smoke/probe runs **only after a discovery checkpoint** (durable-state
save → session restart). Classify the block by its true cause:

- If the harness simply has not **discovered** the newly-added or changed files yet (they exist
  but need a restart), that is a **session/discovery gate**.
- If the assistant's tool surface has **no authorized addressable route** to the custom agent
  (resolved `fresh_worker: none`), that is a **missing-capability block, reason class (b)** —
  it requires the pasted command + error receipt, and a mere session restart will NOT resolve it.

Either way, record a `[B]` with a **linked follow-up** and a **named resume point** whose probe
exercises the **same orchestrator-originated dispatch route** the delegation will use in execution
(not merely a user-launched `/name` invocation, which proves discovery but not autonomous
delegation). An undiscovered/unaddressable agent is **never a silent pass**, and a `[B]` never
counts as AC satisfaction — the criterion is met only by a passing live probe.
