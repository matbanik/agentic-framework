# Build Plan

> Copy to `docs/BUILD_PLAN.md` (or your Spec path from Block D3) and keep the AUTOGEN
> markers. `tools/meu_status.py render` fills the regions from `.agent/context/meu-status.yaml`.
> Fill the rest with `/build-plan-authoring bootstrap`; until then the `[FILL: …]` prompts are
> harmless and the AUTOGEN regions already work.

Status: Draft

## Purpose

[FILL: what is being built, for whom, in two or three sentences.]

## Architecture and Dependency Rule

[FILL: the project's building blocks in its own vocabulary, and the rule for which block may depend on which. A small diagram helps.]

## Build Phases

Phases are numbered in dependency order. A phase spec is the authority for its phase; if this table disagrees with a spec, the spec wins and this table is corrected.

| Phase | Name | Outcome | Depends on | Spec |
|-------|------|---------|------------|------|
| [FILL: 1] | [FILL] | [FILL: one sentence] | [FILL: phase numbers or —] | [FILL: link to build-plan/NN-name.md] |

## Phase Status Tracker

<!-- BEGIN AUTOGEN:meu-status:phase-tracker -->
_(empty — run render after phases exist)_
<!-- END AUTOGEN:meu-status:phase-tracker -->

## MEU Summary

<!-- BEGIN AUTOGEN:meu-status:summary -->
_(empty — run render after MEUs exist)_
<!-- END AUTOGEN:meu-status:summary -->

## Golden Rules

[FILL: the handful of non-negotiables every phase inherits. Keep it short enough to be read every session.]

## Index

**Phase specs**

- [FILL: link to each build-plan/NN-name.md]

**Reference**

- [FILL: link to build-plan/build-priority-matrix.md and any other reference files]

## Notes

Hand-written narrative stays outside the markers. Optional hub sections (locked decisions, open
tensions, inputs, validation command) are described in `.agent/workflows/build-plan-authoring.md`.
