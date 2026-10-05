---
description: Author or extend the build plan — the hub (docs/BUILD_PLAN.md) plus ordered phase specs in docs/build-plan/ — by deriving phases from the project's own architecture and dependency rule. Three modes (bootstrap, add-phase, amend). Produces draft specs that feed /session-grouping. PLANNING-only, no code, no commit.
---

# Build Plan Authoring Workflow

Use this workflow to create or grow the **Spec** the rest of the lifecycle reads: a slim hub that states the architecture and indexes the plan, one spec file per phase, and the priority matrix that orders the work. Invoke it as `/build-plan-authoring <mode> <subject>`:

| Mode | When | Subject |
|------|------|---------|
| `bootstrap` | No build plan exists yet (new project, or a project adopting the framework) | the product/architecture sources to plan from |
| `add-phase` | The plan exists and needs a new phase or sub-phase (a feature, a remediation batch from `/session-grouping` A3) | the feature, findings doc, or research folder |
| `amend` | An existing phase spec is wrong or stale | the phase id and what changed |

This is a **PLANNING-phase-only** workflow. It writes specification documents and nothing else: no production code, no MEU registration (that is `/session-grouping` Stage A), no commit. It adds **no new HARD gate**. The lifecycle already makes the human the author-or-reviewer of the Spec (`development-lifecycle.md` Phase 2), so the workflow ends by presenting the draft and any open decisions at that existing stop.

**The one rule that shapes everything below:** phases come from *this project's* building blocks and the dependencies between them. The framework ships no phase list. `.agent/docs/build-plan-patterns.md` shows how other projects were cut, and it is opened only after you have your own cut (Step 5), because a decomposition copied from an example describes the example's architecture, not yours.

## Design Principles

1. **Derive, don't transplant.** Every phase must be justified by a node or path in the project's dependency graph, never by "the example had one".
2. **Dependency order is the numbering.** A phase's prerequisites all carry lower numbers. No forward dependencies.
3. **Each kind of information has one home.** Architecture and rules live in the hub; behaviour and acceptance criteria live in the phase spec; status lives in `meu-status.yaml` and is rendered, never typed. When hub and phase spec disagree, the phase spec wins and the hub is corrected.
4. **Smallest plan that prevents an expensive misunderstanding.** A section with nothing to say is deleted, not filled. Optional sections are added when a named reader needs them.
5. **Never write a guess as a requirement.** Every acceptance criterion carries a source label (`Spec` / `Local Canon` / `Research-backed` / `Human-approved`). What cannot be labeled is written as `[NEEDS DECISION: …]` and handled through `.agent/docs/human-decision-protocol.md`.
6. **Verifiable or it is not a criterion.** Each exit criterion names the command or observation that proves it.

## Prerequisites

Read in order:

1. `AGENTS.md` §Planning Contract and the source-label taxonomy
2. The project profile — especially D3 (where the Spec lives) and the validation commands (D6)
3. `.agent/docs/human-decision-protocol.md` (every choice in Steps 2–6 runs through it)
4. Research inputs, when present: `docs/research/`, `_inspiration/` (outputs of `/pre-build-research` and `/inspiration-research`)
5. The existing code and docs, for a project that is already partly built
6. `add-phase` / `amend` only: the hub, the target or neighbouring phase specs, `docs/build-plan/build-priority-matrix.md`, and `.agent/context/meu-status.yaml`
7. Templates: `.agent/templates/BUILD_PLAN-STUB.md`, `PHASE-SPEC-TEMPLATE.md`, `BUILD-PRIORITY-MATRIX-TEMPLATE.md`

Do **not** read `.agent/docs/build-plan-patterns.md` yet.

Paths below use the defaults (`docs/BUILD_PLAN.md`, `docs/build-plan/`). If D3 names a different Spec location, use it throughout and pass it to the validator with `--hub` / `--plan-dir`.

---

## BOOTSTRAP

### Step 1 — Gather what is already decided

List, with a source label each, what the project already knows: the product goal and who it is for, the constraints (stack, platforms, compliance, things that must not change), and any decisions already taken. Note what is missing. If the goal or the main constraints cannot be sourced, stop and ask — a plan built on an invented goal is waste. If an area needs outside knowledge, run `/pre-build-research` for it before continuing.

### Step 2 — Name the building blocks and the dependency rule

In the project's own vocabulary, list the blocks the system is made of: layers, services, pipeline stages, packages, modules, device firmware and host tools, chapters, workflows — whatever the architecture actually has. For an existing codebase, read them off the code rather than off a diagram of how it was meant to be.

Then state the **dependency rule**: which block may know about which. One or two sentences plus a small diagram. Examples of the *form* (not of the content): "inner blocks never import outer ones", "stages only read the previous stage's output", "plugins depend on the host API and never on each other".

If the project has no such rule yet, choosing one is the first real decision of the plan. It is usually a one-way door, so it normally goes to the human as a Decision Brief.

### Step 3 — Draw the graph and find the thin end-to-end path

Using `sequential-thinking`:

1. Write the block dependency graph and sort it into tiers (a block sits one tier above the deepest thing it depends on).
2. Identify the **thin end-to-end path**: the smallest piece of real behaviour that passes through every block a user-visible result needs. It proves the blocks connect before any of them is built wide.
3. List the capabilities the product must have, and for each, which blocks it touches.

### Step 4 — Cut the phases

Two kinds of phase exist, and most plans use both:

- **Foundation phase** — builds one block (or a tier) that many others depend on. Justified when the block is cheaper or safer to build in one pass, or when nothing above it can be verified without it.
- **Slice phase** — delivers one capability through every block it touches, in one spec. Justified whenever the blocks it needs already exist to the required depth.

Choose per region of the graph. Common outcomes are "foundation phases up to the thin end-to-end path, then slices", "slices from the start", and "deltas against an existing system" for a project that is already built. None is the default.

Test every candidate phase:

| Test | Question |
|------|----------|
| One outcome | Can its purpose be said in one sentence without "and"? |
| Provable alone | Is there an exit criterion that can be run when this phase finishes, without waiting for a later one? |
| Ordered | Do all its prerequisites come earlier? |
| Sized | Is it one to a few build sessions? If more, split it (sub-phases take a letter suffix: `04a`, `04b`). If less than one MEU, merge it. |
| Recognisable | Would the human recognise the name as a thing they asked for or need? |

Number the phases in dependency order. Record in one or two lines each the decompositions you rejected and why; that record goes in the Decision Log.

### Step 5 — Stress-test against the patterns (examples enter here)

Now read `.agent/docs/build-plan-patterns.md`. Use it for two things only:

- **Challenge your cut.** Find the pattern closest to your architecture and one unlike it. What does each do that you did not? Adopt a difference only if your own graph supports it.
- **Pick optional sections and reference files.** The patterns doc lists what other plans added and what need each addition served.

If your phase list now matches an example name-for-name, treat that as a warning, not a confirmation: re-justify each phase from Step 3 or redo Step 4.

### Step 6 — Decide what must be decided

Run every open choice from Steps 2–5 through `.agent/docs/human-decision-protocol.md`: precedent sweep, web research, obviousness test. Choices that pass are made and logged as `autonomous`. The rest become Decision Briefs. Typical human-gated items at this stage: the dependency rule itself, a stack choice that is costly to reverse, product scope (what version 1 leaves out), and any governance number.

Do not block on the briefs. Continue with the recommended option as the working default, mark every place that depends on it `[NEEDS DECISION: D-n]`, and present the briefs at the end (Step 10).

### Step 7 — Write the hub

Copy `.agent/templates/BUILD_PLAN-STUB.md` to the hub path and fill it. Keep the two AUTOGEN regions exactly as shipped; `tools/meu_status.py render` owns them.

Hub — required core (+ optional):

| # | Section | Req? |
|---|---------|:----:|
| 1 | Purpose — what is being built, for whom, in two or three sentences | ✅ |
| 2 | Architecture and dependency rule — the blocks, the rule, a small diagram | ✅ |
| 3 | Build phases — table: phase · name · outcome · depends on · spec link | ✅ |
| 4 | Phase status tracker / MEU summary — the AUTOGEN regions | ✅ |
| 5 | Golden rules — the handful of non-negotiables every phase inherits | ✅ |
| 6 | Index — links to every phase spec and reference file | ✅ |
| 7 | Locked decisions — table: topic · decision · source label · owning phase | optional |
| 8 | Open tensions — known conflicts between sources, each with an owner | optional |
| 9 | Inputs — research and inspiration files the plan drew on | optional |
| 10 | Validation — the command that checks the plan | optional |

The hub stays an index. Behavioural detail, code, and per-MEU rows belong in phase specs.

### Step 8 — Write the phase specs

One file per phase from `.agent/templates/PHASE-SPEC-TEMPLATE.md`, named `NN-kebab-name.md` (sub-phases `NNx-kebab-name.md`, linking to their parent). Write in dependency order; the first phases in full, later ones at least to required-core depth so the plan's shape is reviewable. A later phase may be honestly thin — say so in its Goal rather than padding it.

Phase spec — required core (+ optional):

| # | Section | Req? |
|---|---------|:----:|
| H | Header line: link to hub · Prerequisites · Outputs | ✅ |
| 1 | Goal — the single outcome and why it comes at this point | ✅ |
| 2 | Scope and Out of scope — including tempting adjacent work, and where it is planned instead | ✅ |
| 3 | Work breakdown — units of work in build order; each with source-labeled, verifiable acceptance criteria | ✅ |
| 4 | Exit Criteria — what is true when the phase is done, with the proving command or observation | ✅ |
| 5+ | Contract detail, design decisions, open decisions, boundary inputs, wiring checklist, test plan, execution order, deferred work, sources, addenda | optional — see template |

Rules for the content:

- Acceptance criteria describe observable behaviour, each with its source label. Unknowns are `[NEEDS DECISION: …]`.
- Work-breakdown rows are sized to become MEUs, but this workflow assigns **no MEU ids**; `/session-grouping` Stage A does.
- Name the files, modules, or interfaces a unit is expected to touch when you know them. Do not invent them when you do not.

### Step 9 — Write the reference files

- `build-priority-matrix.md` (required; `/session-grouping` reads it) from `.agent/templates/BUILD-PRIORITY-MATRIX-TEMPLATE.md`: every work-breakdown row once, in global build order, grouped into priority bands.
- `00-overview.md` (recommended once there are more than a few phases): the dependency diagram, the build order, and the vocabulary shared across phases.
- Anything else only when Step 5 identified a reader for it.

### Step 10 — Validate, then hand over

```
rtk uv run python tools/validate_build_plan.py *> {{RECEIPTS_DIR}}/build-plan-validate.txt; Get-Content {{RECEIPTS_DIR}}/build-plan-validate.txt | Select-Object -Last 30
```

Fix every error. Read the warnings: a `[FILL: …]` left from a template is a section to write or delete, and the `[NEEDS DECISION]` count must equal the open briefs.

Then report to the human, in this order: the phase table; the rejected decompositions; the Decision Log entries for autonomous choices; the Decision Briefs for human-gated ones (protocol §5 format, recommendation first); the validator result. Mark the hub `Status: Draft` until the human accepts the plan, then `Status: Active`. End the turn if briefs are open; otherwise the next step is `/session-grouping <phase id>` for the first phase.

---

## ADD-PHASE

1. **Locate it in the graph.** Which existing blocks and phases does the new work depend on, and what depends on it? That fixes its number: a new top-level number if it stands alone, a letter suffix under the phase it extends or remediates.
2. **Check it is a phase.** Apply the Step 4 tests. Work that fails "Sized" downward belongs as new rows in an existing spec (use `amend`).
3. **Decide what must be decided** (Step 6).
4. **Write the spec** (Step 8). For remediation phases, add a findings → work-unit traceability table so every finding has a home.
5. **Update the hub and matrix**: phase table row, index link, matrix rows. Leave the AUTOGEN regions alone.
6. **Validate and hand over** (Step 10). The usual next step is `/session-grouping <new phase id>`.

## AMEND

1. Change the phase spec first, since it is the authority.
2. Do not silently rewrite criteria that work has already been planned or built against. Add a dated addendum, or mark the old text superseded with a pointer to the new, so plans and handoffs that cite it still resolve.
3. If the change removes or defers work, say where it went (another phase, or a "Deferred" section with a reason).
4. Propagate to the hub and matrix, then run Step 10. If registered MEUs are affected, name them in the report; changing their status is not this workflow's job.

---

## Naming (canonical)

```
docs/BUILD_PLAN.md                         hub
docs/build-plan/00-overview.md             cross-phase overview
docs/build-plan/NN-kebab-name.md           phase spec
docs/build-plan/NNx-kebab-name.md          sub-phase spec (links to NN-…)
docs/build-plan/build-priority-matrix.md   global build order
docs/build-plan/{topic}.md                 other reference files (no number prefix)
```

Two-digit numbers, assigned in dependency order. Numbers are never reused; a withdrawn phase keeps its file with a superseded note.

## Exit Criteria

1. Hub exists with all required-core sections and intact AUTOGEN markers.
2. Every phase in the hub's table has a spec file with the required core; every spec is reachable from the hub.
3. Every acceptance criterion carries a source label or a `[NEEDS DECISION]` marker tied to a brief.
4. `build-priority-matrix.md` lists every work-breakdown row once.
5. `tools/validate_build_plan.py` exits 0.
6. Decision Log and any Decision Briefs were presented. No code written, no MEU registered, no commit.

## Output

A draft build plan (hub, phase specs, matrix, optional references) plus a decision record, ready for human review and then `/session-grouping`.
