# Build Priority Matrix

> Part of [FILL: link to the hub, normally `../BUILD_PLAN.md`]. The global build order: every work-breakdown unit from
> every phase spec appears here exactly once. `/session-grouping` reads this file.

<!--
How to use this template (delete this comment in the real file):
- One row per unit of work. Order numbers are bold, unique, and ascending in build order; a unit
  inserted later takes a letter suffix (**3a**) rather than renumbering everything after it.
- Bands group rows by priority. Name and count the bands to suit the project; the two below only
  show the table shape.
- The MEU column stays empty until `/session-grouping` registers the unit. Status is not tracked
  here: it is rendered into the hub from `.agent/context/meu-status.yaml`.
-->

## How to read this

[FILL: one or two sentences on what puts a unit in an earlier band for this project: dependency depth, risk, user value, a deadline.]

## [FILL: band name, e.g. the work everything else stands on]

| Order | Unit | Phase spec | Depends on | MEU |
|-------|------|------------|------------|-----|
| **1** | [FILL: unit name] | [FILL: link to phase spec section] | — | |

## [FILL: next band name]

| Order | Unit | Phase spec | Depends on | MEU |
|-------|------|------------|------------|-----|
| **2** | [FILL: unit name] | [FILL: link to phase spec section] | [FILL: order numbers] | |
