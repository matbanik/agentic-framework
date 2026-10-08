# Model Delegation Policy — Builder vs Coordinator (Harness-Conditional)

> **Canonical routing matrix:** [`.agent/docs/model-routing.md`](model-routing.md) is the source of truth for the full routed stack (3 model tiers — Coordinator / Builder / Router — plus an external reviewer and an isolated-worker execution mode) and the independent-reviewer chain. **This file is the detailed work-class taxonomy *within* the Coordinator and Builder tiers** — which specific tasks are "mechanical" (delegate) vs "correctness" (keep).
>
> **Harness-conditional class resolution (Q1–Q2, 2026-07-22):** the `coordinator` and `builder` classes resolve per harness, and the bindings differ between harnesses. Which snapshot each class binds to lives in the live registry home you instantiate (see [`.agent/INSTANTIATE.md`](../INSTANTIATE.md)) and must be resolved, not restated here.
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
- Domain / service correctness MEUs — anything with real correctness or security
  risk. The test is whether a wrong answer would be *silently* wrong rather than
  loud: money and quantity arithmetic, identity resolution, dedup/merge rules,
  adapters to external systems, transaction/unit-of-work boundaries, and
  authorization decisions all qualify.
- Implementor self-verification + pre-handoff review.

## How to delegate

- **In-harness route (only where an *assistant-addressable* `fresh_worker` resolves):** dispatch
  the mechanical class to the `{{PROJECT_NAME}}-builder` subagent and verbose validation to the
  `{{PROJECT_NAME}}-verifier` subagent via Claude Code's Agent tool + `.claude/agents/` (`model:` lines
  generated from the registry's `builder` / `verifier` bindings). The detection, decision table, dispatch-prompt contract, and result-acceptance rules live in
  [`../skills/subagent-delegation/SKILL.md`](../skills/subagent-delegation/SKILL.md). Resolve
  `fresh_worker` from the harness profile, never from directory presence.
- **Agent files pin `model:` and `effort:`.** `{{PROJECT_NAME}}-builder` (`builder` class, `medium`) takes the
  mechanical class; `{{PROJECT_NAME}}-verifier` (`verifier`, `low`) runs validation read-only;
  `{{PROJECT_NAME}}-scout` (`scout`, `low`) takes read-only search fan-out and returns paths + excerpts;
  `{{PROJECT_NAME}}-peer_reviewer` (`peer_reviewer`, `high`) gives an advisory adversarial read of a
  correctness-critical diff or plan — findings only, never a verdict file, never `approved`.
  `model:` is generated from the registry (`resolve_model.py sync`; see `.agent/INSTANTIATE.md`);
  `effort:` is pinned by hand — keep it equal to the class's `effort_default`, and add a test that
  fails when a pin drifts.
- Do not set `CLAUDE_CODE_EFFORT_LEVEL`: it overrides every agent file's `effort:` pin (Claude Code
  docs, sub-agents frontmatter). Set the coordinator's own effort for the session with `/effort`.
- **Advisor.** Where the resolved harness's `advisor` flag ([`harness-profiles.md`](harness-profiles.md)) is `opus`, the coordinator may consult the harness-native advisor (`/advisor opus`, the `advisorModel` setting) before an irreversible or architecture decision. Its answer is advisory input to the coordinator — never a review verdict, never human approval, never a substitute for the `independent_reviewer`. Where the flag is `none`, escalate through `{{PROJECT_NAME}}-peer_reviewer`, or the `architect` class when the grouping row flags architecture risk. <!-- model-slug-ok: `opus` is the value set of Claude Code's own advisor surface (`/advisor opus`, `advisorModel`), a harness enum, not a routing pin -->
- Keep the harness-resolved `coordinator` as the main-loop orchestrator; reserve frontier effort on the `independent_reviewer` chain for the correctness class.
- **Never delegate** the correctness class, review verdict authorship, commit/push, or any
  human-approval gate — those stay inline on the `coordinator` or on the external reviewer chain.

## Why

The 2-week audit (21 reflections, 31 reviews, 18 measured sessions) found **116 paid review rounds**, the single largest process cost — and most findings were mechanical (count reconciliation, boundary validation, variant/size swaps, raw-button→primitive). These are low-risk and downgradeable. Reserve coordinator-tier effort for correctness MEUs and the adversarial `independent_reviewer`; route the mechanical class to `builder` to cut cost and avoid overthinking.
