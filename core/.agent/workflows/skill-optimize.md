---
description: On-demand optimizer that evolves a skill/workflow/instruction doc from past-session evidence — propose bounded edits, gate them with a cross-vendor LLM-judge over held-out digests, and STAGE accepted edits into a protected LEARNED region for human adoption.
---

# Skill-Optimize Workflow

Recreates SkillOpt's instruction-optimization discipline **natively and on-demand**
(no `skillopt` dependency): `harvest → propose (bounded) → gate (cross-vendor judge,
held-out) → buffer → stage`. It is **human-triggered**, never nightly, and it
**never edits a production doc** — accepted edits are staged into a protected
LEARNED region for a human to adopt by hand.

Use this for prompts like:
- "Optimize this new skill against representative tasks before I rely on it" (`--new`)
- "Evolve AGENTS.md / this SKILL.md from the friction in recent sessions" (`--evolve`)

> Backed by the deterministic toolkit `tools.skill_optimize` (validated boundaries,
> gate logic, buffer, protected-region writer). This workflow drives the *creative*
> LLM steps and feeds their output back through that toolkit.

// turbo-all
// NOTE: non-destructive reads + the package's own confined writes (staging only).
// Never auto-commit (AGENTS.md §Commits). Never write a production instruction doc.

---

## Two modes

| Mode | Invocation | What it does |
|------|-----------|--------------|
| **`--new`** (forward) | `python -m tools.skill_optimize --new <skill.md> --tasks <tasks.json>` | Forward-optimize a freshly authored skill/workflow against representative tasks — *especially for new features*. |
| **`--evolve`** (backward) | `python -m tools.skill_optimize --evolve <doc.md>` | Consolidate an existing instruction doc from past-session friction filtered to that doc. |

> ⚠️ **Predict-not-execute limitation (Q2).** The gate's judge **predicts** instruction
> quality from `(instructions + task digest)`; it never re-runs the agent — in **either**
> mode. `--new` edits are the most counterfactual (no real history for a brand-new skill),
> so they are marked **lower confidence** in the staging report.

---

## Prerequisites

Read:
1. `AGENTS.md` (§Human Approval Gate, §Deletion Budget, §Dual-Agent Workflow)
2. `.agent/skills/skill-optimizer/SKILL.md` — bounded-edit format, rubric, buffer + LEARNED contract
3. `.agent/skills/skill-optimizer/rubric-templates.md` — the LLM-judge rubric (gate refuses without it)
4. `.agent/skills/cli-dispatch/SKILL.md` — how to dispatch the optimizer + judge

---

## Step 0 — Preflight (deterministic)

```powershell
uv run python -m tools.skill_optimize --evolve <doc.md> --budget 4 *> {{RECEIPTS_DIR}}/skillopt-preflight.txt; Get-Content {{RECEIPTS_DIR}}/skillopt-preflight.txt
```

This **harvests** the corpus (handoffs + reflections), builds the deterministic
held-out train/val/test split, runs the sample-floor / ledger checks, and writes a
run manifest to `.agent/context/skill-optimizer/staging/`. If val/test are below
`N_min` the gate would `block_for_human` — stop and report that.

---

## Step 1 — Harvest & reflect (optimizer LLM)

Dispatch the **optimizer** — **Claude Sonnet 5 @ medium** (mechanical class;
`model-delegation.md`) — over the **train** split + the target doc. Ask it to emit
**bounded `add/delete/replace` edits** (each with a rationale and a support count).
Validate/dedup/clip to the budget with `propose.dedup_and_clip` (≤4 — the "textual
learning rate"). Drop any edit suppressed by the rejected-edit **buffer**
(`buffer.is_suppressed`).

## Step 2 — Gate (cross-vendor judge, held-out)

Produce the candidate via `propose.produce_candidate` (applies edits to a COPY).
Dispatch the **judge** — **GPT-5.6 Sol @ high**, a DIFFERENT model family than the
optimizer (Claude Opus 5 fallback only if it does NOT collide with the optimizer
family; else `block_for_human`). Score **candidate-vs-baseline pairwise, both orders**,
over the **val** set, then the untouched **test** slice, via `gate.run_gate`:
- **accept** iff candidate wins val by the ε margin AND does not regress test;
- **reject** → record to the buffer (`buffer.append_rejection`) so it is not retried;
- **insufficient_evidence / blocked_for_human** → stop and report.

## Step 3 — Stage (protected LEARNED region; human adoption)

For an **accepted** candidate, `stage.stage` writes the LEARNED block into a
**staging copy + report** under `.agent/context/skill-optimizer/staging/` — the
production doc is opened read-only and **never modified**. Safety docs are fenced:
`AGENTS.md` needs `--allow-safety-doc` + a deletion-budget offset; **`GUARDRAILS.md`
is always `blocked_for_human`**.

## Step 4 — Hand off to the human

Present the staging report. **Human adoption is manual and terminal**: a human
reviews the staged LEARNED block and copies it into the production doc by hand. The
tool has no `--adopt`/`--apply` path (AGENTS.md §Human Approval Gate; GUARDRAILS SIGN 1/3).

---

## Hard Rules

1. **Never modify a production instruction doc.** Output is a staging copy + report only.
2. **The gate is cross-vendor.** Optimizer family ≠ judge family, checked even after a fallback.
3. **Held-out discipline.** The test slice is scored once per `(target, corpus, seed)`; the consumption ledger blocks reuse.
4. **Rubric required.** No gate run without a schema-valid rubric.
5. **Human adoption is terminal.** No auto-merge, ever. Safety docs are extra-fenced.
6. **Never auto-commit.**

---

## Output Contract

- Preflight manifest (corpus size, split, sufficiency)
- Per-candidate gate result (accept/reject/blocked, val wins, test mean delta)
- Staging report path(s) + the LEARNED block proposed for human adoption
- Buffer updates (rejected edits recorded)
