---
name: Skill Optimizer
description: Domain skill for the on-demand /skill-optimize loop — bounded add/delete/replace edit format, the cross-vendor LLM-judge rubric, the rejected-edit (negative-memory) buffer, the held-out test-consumption ledger, and the protected LEARNED-region staging contract.
---

# Skill Optimizer

Toolkit + contract for evolving an instruction doc (skill, workflow, AGENTS.md,
emerging-standards) the way SkillOpt evolves a "trainable weight" — but on-demand
and gated by held-out evidence. Driven by the `/skill-optimize` workflow over the
`tools.skill_optimize` package.

## When to Use

- Hardening a **new** skill/workflow before relying on it (`--new`).
- Consolidating an **existing** instruction doc from accumulated session friction (`--evolve`).
- NOT for ad-hoc rewrites — every change must clear the validation gate and be staged for human adoption.

## Bounded edit format (the "textual learning rate")

The optimizer emits `EditOp` objects; at most `budget` (default 4, range 1–4)
survive dedup + clip. Wholesale rewrites are forbidden (they cause context
collapse — ACE arXiv:2510.04618).

```json
{"op": "replace", "anchor": "<unique existing text>", "text": "<new text>", "rationale": "<why>", "support_count": 1}
{"op": "delete",  "anchor": "<unique existing text>", "rationale": "<why>"}
{"op": "add",     "anchor": "<existing text to insert after>", "text": "<new text>", "rationale": "<why>"}
```

- An op whose `anchor` does not resolve in the target is **rejected, not applied**.
- Edits are applied to a COPY (`propose.produce_candidate`) — the target is never mutated.

## Validation gate (cross-vendor, held-out)

- Judge model family **must differ** from the optimizer family (Sonnet 5 → GPT-5.6-sol).
  A fallback that would collide (Claude judge + Claude optimizer) → `blocked_for_human`.
- **Pairwise, both orders, averaged** (cancels position bias — arXiv:2406.07791).
- **accept iff** candidate wins val by ε (default ⌈0.6·N_val⌉) **AND** test mean Δ ≥ 0.
- **N_min** floor (default 5): too few held-out digests → `insufficient_evidence`.
- Requires a schema-valid rubric (`rubric-templates.md`) — no silent default.
- The **test-consumption ledger** (`test-consumption.jsonl`) blocks reusing the same
  held-out test slice across runs.

## Rejected-edit buffer (negative memory)

Gate-rejected edits are hashed and stored in `rejected-edits.jsonl` so they are not
re-proposed — **expirable** (default 30-day TTL) and **human-overridable** to avoid
self-reinforcing error (Reflexion/ExpeL analogy, arXiv:2603.07670).

## Protected LEARNED region (staging contract)

Accepted edits are written ONLY between `<!-- LEARNED:START id=... -->` and
`<!-- LEARNED:END -->`, into a **staging copy + report** — never the production doc.

- **Human adoption is manual and terminal** — no `--adopt`/`--apply` path.
- `GUARDRAILS.md` staging is **always** `blocked_for_human`.
- `AGENTS.md` staging needs `--allow-safety-doc` **and** a deletion-budget offset
  (each LEARNED addition names a `DELETE:`/`MERGE:` target; net rule count must not grow).

## Source-label discipline

Every acceptance criterion / rubric dimension carries `Spec | Local Canon |
Research-backed | Human-approved` — never bare "best practice". The ε, `N_min`, and
buffer-TTL constants are tunable defaults pending human confirmation (Q4).
