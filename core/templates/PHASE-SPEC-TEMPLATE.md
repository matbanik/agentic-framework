# Phase [FILL: N]: [FILL: phase name]

> Part of [FILL: link to the hub, normally `../BUILD_PLAN.md`] | Prerequisites: [FILL: links to earlier phase specs, or "None"] | Outputs: [FILL: what later phases can rely on once this is done]

<!--
How to use this template (delete this comment in the real spec):
- Sections 1-4 are the required core. Everything under "Optional sections" is a menu:
  keep a section only if this phase needs it, and delete the rest. Do not leave empty headings.
- Replace every [FILL: ...]. Write anything you cannot source as [NEEDS DECISION: ...] and
  raise it through .agent/docs/human-decision-protocol.md.
- Source labels: Spec / Local Canon / Research-backed / Human-approved.
- This template carries no domain content on purpose. Section ideas and the needs behind them
  are in .agent/docs/build-plan-patterns.md (read it after you have drafted the core).
-->

## Goal

[FILL: the single outcome of this phase in one or two sentences, and why it comes at this point in the build order.]

## Scope

**In scope**

- [FILL: capability or block this phase delivers]

**Out of scope**

- [FILL: tempting adjacent work, and the phase where it is planned instead (or "not planned")]

## Work Breakdown

Units are listed in build order and sized to become one MEU each. Ids are assigned later by `/session-grouping`.

| # | Unit | Touches | Depends on |
|---|------|---------|------------|
| 1 | [FILL: short name] | [FILL: files / modules / interfaces, if known] | [FILL: unit # or phase, or "none"] |

### Unit 1 — [FILL: short name]

[FILL: what this unit delivers, in a few sentences.]

**Acceptance criteria**

| AC | Criterion (observable behaviour) | Source |
|----|----------------------------------|--------|
| 1.1 | [FILL: verifiable statement] | [FILL: Spec / Local Canon / Research-backed / Human-approved + pointer] |

## Exit Criteria

The phase is done when all of these hold:

| # | Criterion | Proven by |
|---|-----------|-----------|
| 1 | [FILL: what is true] | [FILL: command or observation] |

<!-- ───────────── Optional sections: keep only what this phase needs ───────────── -->

## Contract

[FILL: user-visible or caller-visible behaviour: states, inputs, outputs, errors.]

## Design Decisions

| Topic | Decision | Source | Why |
|-------|----------|--------|-----|
| [FILL] | [FILL] | [FILL: source label] | [FILL] |

## Open Decisions

| ID | Question | Recommended default | Blocks |
|----|----------|---------------------|--------|
| D-[FILL] | [FILL] | [FILL] | [FILL: unit # or "nothing"] |

## Boundary Inputs

| Input | Enters at | Validation | On failure |
|-------|-----------|------------|------------|
| [FILL] | [FILL] | [FILL] | [FILL] |

## Wiring Checklist

- [ ] [FILL: a connection between blocks that must exist for the feature to work end to end]

## Test Plan

[FILL: test levels used, shared fixtures, and what must be seen failing before it passes.]

## Execution Order

[FILL: suggested grouping of units into sessions, if the table order is not enough.]

## Deferred

| Item | Why deferred | Destination |
|------|--------------|-------------|
| [FILL] | [FILL] | [FILL: phase, or "unplanned"] |

## Sources

- [FILL: document, research file, or URL each labeled criterion relies on]

## Addenda

<!-- Dated changes after work has been planned or built against this spec. Newest first. -->
