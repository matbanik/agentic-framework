# Model Delegation Policy — Builder vs Coordinator (Harness-Conditional)

> **Canonical routing matrix:** [`.agent/docs/model-routing.md`](model-routing.md) is the source of truth for the full routed stack (3 model tiers — Coordinator / Builder / Router — plus an external reviewer and two execution modes) and the independent-reviewer chain. **This file is the detailed work-class taxonomy *within* the Coordinator and Builder tiers** — which specific tasks are "mechanical" (delegate) vs "correctness" (keep).
>
> **Harness-conditional class resolution (Q1–Q2, 2026-07-22):** the `coordinator` and `builder` classes resolve per harness — Cursor vs Claude Code bindings differ. Which snapshot each class binds to lives in the live registry home you instantiate (see [`.agent/INSTANTIATE.md`](../../../.agent/INSTANTIATE.md)) and must be resolved, not restated here.
>
> **Source:** `Local Canon + Human-approved` (2026-06-13 `instruction-set-optimization`, decision D5; Q1–Q8 2026-07-22). Evidence: `docs/execution/plans/2026-06-13-instruction-set-optimization/audit-findings.md` §6. Effort guidance: `.agent/skills/cli-dispatch/SKILL.md` §Reviewer Effort Policy.

Two work classes run under one heavyweight protocol. Match the **class + effort** to the work class instead of running everything on the coordinator tier at high effort.

## Delegate to the builder tier (low/medium effort) — the mechanical class

The `builder` class (and `verifier`, which extends it for read-only validation) handles mechanical work. Effort research shows low/medium is the right depth for well-specified mechanical work (higher effort invites overthinking, not quality):

- **GUI style migrations** (SM-class): lookup target-spec → swap design token / raw `<button>`→`<Button>` → verify.
- **Predictable correction categories:** count/tracker reconciliation, design-token swaps, stale-reference / cross-doc sweeps, boundary `Field(ge=0)` additions, lint / unused-import cleanup.
- **Doc-only work:** `BUILD_PLAN.md` / `meu-registry.md` status updates, naming sweeps.
- **Test-fixture construction** (OFX/QIF/CSV samples), allowlist / member-count test updates.
- **Closeout-artifact drafting** from template (session digest, metrics rows).
- **The pre-review mechanical self-check pass** (see `pre-handoff-review/SKILL.md` §Step 0).

## Keep on the coordinator (high/xhigh) — the correctness class

The `coordinator` class holds planning, correctness-critical reasoning, and orchestration (resolve per harness via the registry).

- Planning + FIC authoring + spec-sufficiency.
- Domain / service correctness MEUs (broker adapters, dedup, identifier resolver, import routes, UoW lifecycle) — anything with real correctness or security risk.
- Implementor self-verification + pre-handoff review.

## How to delegate

- **In-harness route (only where an *assistant-addressable* `fresh_worker` resolves):** dispatch
  the mechanical class to the `{{PROJECT_NAME}}-builder` subagent and verbose validation to the
  `{{PROJECT_NAME}}-verifier` subagent via the resolved harness's Agent/`Task` tool — e.g. Claude Code's
  Agent tool + `.claude/agents/` (`model: sonnet`), <!-- model-slug-ok: harness agent-def frontmatter schema uses vendor shorthand, not capability classes --> or Cursor's assistant-addressable `Task` tool
  (`{{PROJECT_NAME}}-builder` / `{{PROJECT_NAME}}-verifier`) + `.cursor/agents/` (builder class binding via registry autogen).
  The detection, decision table, dispatch-prompt contract, and result-acceptance rules live in
  [`../skills/subagent-delegation/SKILL.md`](../skills/subagent-delegation/SKILL.md). Resolve
  `fresh_worker` from the harness profile, never from directory presence.
- A `mechanical-edit` subagent with the `builder` class + low/medium effort in its frontmatter.
- `CLAUDE_CODE_EFFORT_LEVEL` per role (low for mechanical-edit subagents; high/xhigh for the reviewer/planner).
- Keep the harness-resolved `coordinator` as the main-loop orchestrator; reserve frontier effort on the `independent_reviewer` chain for the correctness class.
- **Never delegate** the correctness class, review verdict authorship, commit/push, or any
  human-approval gate — those stay inline on the `coordinator` or on the external reviewer chain.

## Why

The 2-week audit (21 reflections, 31 reviews, 18 measured sessions) found **116 paid review rounds**, the single largest process cost — and most findings were mechanical (count reconciliation, boundary validation, variant/size swaps, raw-button→primitive). These are low-risk and downgradeable. Reserve coordinator-tier effort for correctness MEUs and the adversarial `independent_reviewer`; route the mechanical class to `builder` to cut cost and avoid overthinking.
